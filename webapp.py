from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, NotRequired, TypedDict

from flask import Flask, redirect, render_template, request, url_for

from state import load_queue, load_runtime_state, load_tags, save_queue, save_runtime_state, save_tags

APP_ROOT = Path('/srv/music')
app = Flask(__name__)


class Track(TypedDict):
    artist: str
    album: str
    track: str
    position: NotRequired[int | None]
    display: NotRequired[str]


def scan_library() -> List[Dict[str, str]]:
    albums: List[Dict[str, str]] = []
    if not APP_ROOT.exists():
        return albums
    for artist_dir in sorted([p for p in APP_ROOT.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
        for album_dir in sorted([p for p in artist_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
            rel = album_dir.relative_to(APP_ROOT).as_posix()
            albums.append({"artist": artist_dir.name, "album": album_dir.name, "folder": rel})
    return albums


def terminal_title(title: str) -> str:
    return title


def _run_mpc(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ''


def _parse_track_line(line: str, include_position: bool = False) -> Track:
    parts = [part.strip() for part in line.split('\t')]
    if include_position:
        parts += [''] * max(0, 4 - len(parts))
        position, artist, album, track = parts[:4]
        return {
            'position': int(position) if position.isdigit() else None,
            'artist': artist,
            'album': album,
            'track': track,
        }
    parts += [''] * max(0, 3 - len(parts))
    artist, album, track = parts[:3]
    return {
        'artist': artist,
        'album': album,
        'track': track,
    }


def _current_track() -> Track:
    line = _run_mpc(['mpc', 'current', '-f', '%position%\t%artist%\t%album%\t%title%'])
    state = (_run_mpc(['mpc', 'status', '%state%']) or '').splitlines()
    player_state = state[-1].strip().lower() if state else ''
    if not line or player_state == 'stopped':
        return {'position': None, 'artist': '', 'album': '', 'track': '', 'display': 'nothing playing'}

    track = _parse_track_line(line, include_position=True)
    parts = [value for value in [track['artist'], track['album'], track['track']] if value]
    display = ' — '.join(parts) if parts else 'unknown track'
    if player_state == 'paused':
        display = f'{display} [paused]'
    track['display'] = display
    return track


def _current_queue(current_track: Track | None = None) -> List[Track]:
    output = _run_mpc(['mpc', 'playlist', '-f', '%position%\t%artist%\t%album%\t%title%'])
    if not output:
        return []

    queue = [_parse_track_line(line, include_position=True) for line in output.splitlines() if line.strip()]
    if not current_track or current_track.get('position') is None:
        return queue

    current_position = current_track['position']
    if any(item.get('position') == current_position for item in queue):
        return [item for item in queue if item.get('position') is not None and item['position'] >= current_position]

    return queue


def _control_panel_context() -> Dict[str, Any]:
    runtime = load_runtime_state()
    return {
        'runtime': runtime,
        'current_track': _current_track(),
        'title': terminal_title,
    }


def _render_control_panel() -> str:
    return render_template('_control_panel.html', **_control_panel_context())


def _redirect_to_index() -> Any:
    return redirect(url_for('index', q=request.form.get('q', '')))


def _player_command(command: list[str], success_message: str) -> Any:
    runtime = load_runtime_state()
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        runtime['message'] = success_message
    except subprocess.CalledProcessError as exc:
        error = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        runtime['message'] = f"player command failed: {error}"
    save_runtime_state(runtime)

    if request.headers.get('HX-Request') == 'true':
        return _render_control_panel()
    return _redirect_to_index()


@app.route('/')
def index():
    search = request.args.get('q', '').strip().lower()
    albums = scan_library()
    if search:
        albums = [a for a in albums if search in a['artist'].lower() or search in a['album'].lower() or search in a['folder'].lower()]
    queue_state = load_queue()
    control_panel = _control_panel_context()
    current_track = _current_track()
    tags = load_tags().get('tags', {})
    mappings = [{"uid": uid, **cfg} for uid, cfg in sorted(tags.items(), key=lambda item: item[1].get('folder', ''))]
    return render_template(
        'index.html',
        albums=albums,
        current_queue=_current_queue(current_track),
        current_track=current_track,
        queue=queue_state.get('queue', []),
        runtime=control_panel['runtime'],
        mappings=mappings,
        query=request.args.get('q', ''),
        title=terminal_title,
    )


@app.get('/current-queue')
def current_queue_partial():
    current_track = _current_track()
    return render_template(
        '_current_queue.html',
        current_queue=_current_queue(current_track),
        current_track=current_track,
        title=terminal_title,
    )


@app.get('/assigment-queue')
@app.get('/assignment-queue')
def assignment_queue_partial():
    queue_state = load_queue()
    return render_template(
        '_assignment_queue.html',
        queue=queue_state.get('queue', []),
        title=terminal_title,
    )


@app.post('/player/prev')
def player_prev():
    return _player_command(['mpc', 'prev'], 'previous track')


@app.post('/player/toggle-pause')
def player_toggle_pause():
    return _player_command(['mpc', 'toggle'], 'toggled play/pause')


@app.post('/player/next')
def player_next():
    return _player_command(['mpc', 'next'], 'next track')


@app.post('/library/play')
def library_play():
    folder = request.form['folder']
    runtime = load_runtime_state()
    try:
        status = subprocess.run(
            ['mpc', 'status', '%state%'],
            check=True,
            capture_output=True,
            text=True,
        )
        state = status.stdout.strip().splitlines()[-1].strip().lower() if status.stdout.strip() else ''

        if state == 'playing':
            subprocess.run(['mpc', 'crop'], check=False, capture_output=True, text=True)
            subprocess.run(['mpc', 'searchadd', 'filename', folder], check=True, capture_output=True, text=True)
            subprocess.run(['mpc', 'crossfade', '8'], check=True, capture_output=True, text=True)
            subprocess.run(['mpc', 'next'], check=True, capture_output=True, text=True)
            subprocess.run(['mpc', 'crossfade', '0'], check=True, capture_output=True, text=True)
        else:
            subprocess.run(['mpc', 'searchadd', 'filename', folder], check=True, capture_output=True, text=True)
            subprocess.run(['mpc', 'play'], check=True, capture_output=True, text=True)

        runtime['message'] = f'playing {folder}'
    except subprocess.CalledProcessError as exc:
        error = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        runtime['message'] = f'play failed for {folder}: {error}'
    save_runtime_state(runtime)

    if request.headers.get('HX-Request') == 'true':
        return _render_control_panel()
    return _redirect_to_index()


@app.post('/assign/add')
def assign_add():
    folder = request.form['folder']
    queue_state = load_queue()
    queue = queue_state.get('queue', [])
    if not any(item.get('folder') == folder for item in queue):
        queue.append({"action": "play_folder", "folder": folder})
        queue_state['queue'] = queue
        save_queue(queue_state)
        message = f'assignment queued for {folder}'
    else:
        message = f'{folder} already in assignment queue'
    runtime = load_runtime_state()
    runtime['message'] = message
    save_runtime_state(runtime)
    if request.headers.get('HX-Request') == 'true':
        return assignment_queue_partial()
    return _redirect_to_index()


@app.post('/library/queue')
def library_queue():
    folder = request.form['folder']
    runtime = load_runtime_state()
    try:
        subprocess.run(['mpc', 'searchadd', 'filename', folder], check=True, capture_output=True, text=True)
        runtime['message'] = f'queued in playlist {folder}'
    except subprocess.CalledProcessError as exc:
        error = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        runtime['message'] = f'queue failed for {folder}: {error}'
    save_runtime_state(runtime)
    return _redirect_to_index()


@app.post('/queue/remove')
def queue_remove():
    folder = request.form['folder']
    queue_state = load_queue()
    queue_state['queue'] = [item for item in queue_state.get('queue', []) if item.get('folder') != folder]
    save_queue(queue_state)
    runtime = load_runtime_state()
    runtime['message'] = f'removed {folder} from queue'
    save_runtime_state(runtime)
    return redirect(url_for('index'))


@app.post('/mappings/edit')
def mapping_edit():
    uid = request.form['uid'].strip()
    folder = request.form['folder'].strip()
    tags = load_tags()
    mapping = tags.get('tags', {}).get(uid)
    runtime = load_runtime_state()

    if not mapping:
        runtime['message'] = f'mapping for {uid} not found'
    elif not folder:
        runtime['message'] = f'folder cannot be empty for {uid}'
    else:
        mapping['folder'] = folder
        mapping['action'] = 'play_folder'
        save_tags(tags)
        runtime['message'] = f'updated mapping for {uid}'

    save_runtime_state(runtime)
    return redirect(url_for('index'))


@app.post('/mappings/delete')
def mapping_delete():
    uid = request.form['uid']
    tags = load_tags()
    tags.get('tags', {}).pop(uid, None)
    save_tags(tags)
    runtime = load_runtime_state()
    runtime['message'] = f'deleted mapping for {uid}'
    save_runtime_state(runtime)
    return redirect(url_for('index'))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8080'))
    app.run(host='0.0.0.0', port=port, debug=False)

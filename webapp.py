from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, NotRequired, TypedDict

from flask import Flask, Response, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue

from state import RuntimeState, load_queue, load_runtime_state, load_tags, save_queue, save_runtime_state, save_tags

APP_ROOT = Path('/srv/music')
ARCHIVE_ROOT = Path('/srv/music-archive')
app = Flask(__name__)
app.logger.setLevel(logging.INFO)


class Track(TypedDict):
    artist: str
    album: str
    track: str
    position: NotRequired[int | None]
    display: NotRequired[str]


class ControlPanelContext(TypedDict):
    runtime: RuntimeState
    current_track: Track
    title: Callable[[str], str]


class Album(TypedDict):
    artist: str
    album: str
    folder: str
    tracks: List[str]


AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.m4b', '.flac', '.wav', '.ogg', '.opus', '.aac'}


def _album_tracks(album_dir: Path) -> List[str]:
    return [
        track_file.stem
        for track_file in sorted(
            [path for path in album_dir.iterdir() if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS],
            key=lambda path: path.name.lower(),
        )
    ]


def scan_library() -> List[Album]:
    albums: List[Album] = []
    if not APP_ROOT.exists():
        return albums
    for artist_dir in sorted([p for p in APP_ROOT.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
        for album_dir in sorted([p for p in artist_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
            rel = album_dir.relative_to(APP_ROOT).as_posix()
            albums.append({
                "artist": artist_dir.name,
                "album": album_dir.name,
                "folder": rel,
                "tracks": _album_tracks(album_dir),
            })
    return albums


def terminal_title(title: str) -> str:
    return title


def _resolve_album_path(folder: str) -> Path:
    album_path = (APP_ROOT / folder).resolve()
    app_root = APP_ROOT.resolve()
    if album_path == app_root or app_root not in album_path.parents:
        raise ValueError(f'invalid album folder: {folder}')
    return album_path


def _album_export_data() -> List[Dict[str, str]]:
    return [
        {
            'uuid': f"{album['artist']}-{album['album']}",
            'album-name': album['album'],
            'artist-name': album['artist'],
        }
        for album in scan_library()
    ]


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


def _control_panel_context() -> ControlPanelContext:
    runtime = load_runtime_state()
    return {
        'runtime': runtime,
        'current_track': _current_track(),
        'title': terminal_title,
    }


def _search_terms(*parts: str) -> str:
    words: List[str] = []
    for part in parts:
        words.extend(piece for piece in part.lower().split() if piece)
    return ' '.join(words)



def _library_context() -> Dict[str, object]:
    queue_folders = {
        item.get('folder', '')
        for item in load_queue().get('queue', [])
        if item.get('folder')
    }
    mapped_folders = {
        config.get('folder', '')
        for config in load_tags().get('tags', {}).values()
        if config.get('folder')
    }
    assigned_folders = queue_folders | mapped_folders

    albums = [
        {
            **album,
            'track_count': len(album['tracks']),
            'search_terms': _search_terms(album['artist'], album['album']),
            'is_favourite': album['folder'] in assigned_folders,
            'is_assigned': album['folder'] in assigned_folders,
        }
        for album in scan_library()
    ]
    return {
        'albums': albums,
        'title': terminal_title,
    }


def _render_control_panel() -> str:
    return render_template('_control_panel.html', **_control_panel_context())


def _render_library() -> str:
    return render_template('_library.html', **_library_context())


def _redirect_to_index() -> Response:
    return redirect(url_for('index'))


def _player_command(command: list[str], success_message: str) -> ResponseReturnValue:
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
    queue_state = load_queue()
    control_panel = _control_panel_context()
    current_track = _current_track()
    tags = load_tags().get('tags', {})
    mappings = [{"uid": uid, **cfg} for uid, cfg in sorted(tags.items(), key=lambda item: item[1].get('folder', ''))]
    return render_template(
        'index.html',
        current_queue=_current_queue(current_track),
        current_track=current_track,
        queue=queue_state.get('queue', []),
        runtime=control_panel['runtime'],
        mappings=mappings,
        **_library_context(),
    )


@app.get('/control-panel')
def control_panel_partial():
    return _render_control_panel()


@app.get('/library')
def library_partial():
    return _render_library()


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


@app.post('/player/volume-down')
def player_volume_down():
    return _player_command(['mpc', 'volume', '-5'], 'volume down')


@app.post('/player/volume-up')
def player_volume_up():
    return _player_command(['mpc', 'volume', '+5'], 'volume up')


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
            subprocess.run(['mpc', 'clear'], check=True, capture_output=True, text=True)
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
    assigned_folders = {
        config.get('folder', '')
        for config in load_tags().get('tags', {}).values()
        if config.get('folder')
    }

    if folder in assigned_folders:
        message = f'{folder} already assigned'
    elif not any(item.get('folder') == folder for item in queue):
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
    if request.headers.get('HX-Request') == 'true':
        return current_queue_partial()
    return _redirect_to_index()


@app.post('/library/archive')
def library_archive():
    folder = request.form['folder']
    runtime = load_runtime_state()
    is_hx = request.headers.get('HX-Request') == 'true'
    success = False
    app.logger.info('archive requested folder=%r hx=%s remote=%s', folder, is_hx, request.remote_addr)
    try:
        source = _resolve_album_path(folder)
        destination = (ARCHIVE_ROOT / folder).resolve()
        archive_root = ARCHIVE_ROOT.resolve()
        app.logger.info('archive paths source=%s destination=%s', source, destination)
        if destination == archive_root or archive_root not in destination.parents:
            raise ValueError(f'invalid archive destination for {folder}')
        if destination.exists():
            raise FileExistsError(f'{destination} already exists')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))

        artist_dir = source.parent
        try:
            artist_dir.rmdir()
            app.logger.info('removed empty artist directory %s', artist_dir)
        except OSError:
            pass

        status = subprocess.run(['mpc', 'status'], check=True, capture_output=True, text=True)
        if 'Updating DB' not in status.stdout:
            subprocess.run(['mpc', 'update'], check=True, capture_output=True, text=True)

        runtime['message'] = f'archived {folder}'
        success = True
        app.logger.info('archive succeeded folder=%r destination=%s', folder, destination)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        runtime['message'] = f'archive failed for {folder}: {exc}'
        app.logger.exception('archive failed folder=%r', folder)
    save_runtime_state(runtime)
    if is_hx:
        return Response(status=204) if success else Response(runtime['message'], status=500)
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


@app.get('/admin/export-albums')
def admin_export_albums():
    payload = '\n'.join(json.dumps(album) for album in _album_export_data()) + '\n'
    return Response(
        payload,
        mimetype='application/x-ndjson',
        headers={'Content-Disposition': 'attachment; filename=albums-export.jsonl'},
    )


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

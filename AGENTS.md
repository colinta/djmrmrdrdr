# AGENTS.md

- Always restart the web server after any change to the web site.
- Use `systemctl` with the managed service (`musicplayer-web.service`) to restart the web server; do not restart it by launching `webapp.py` directly.
- Using `sudo` to restart `musicplayer-web.service` is allowed when needed.

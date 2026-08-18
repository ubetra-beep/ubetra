# Instructor plugin

Playtime Instructor is a UBETRA-hosted game adapted from
[rororosi/fapinstructor-client](https://github.com/rororosi/fapinstructor-client)
(fork of EroticRide / Fap Instructor; GPL-2.0). The upstream CRA/Auth0/Sentry app
is **not** vendored. The in-app engine lives in `frontend/instructor.js` and talks
only to UBETRA HTTP APIs. Overlay HUD, task packs, and create-game settings follow
the hosted legacy client at fapinstructor.com (local files only; no Scrolller).

License: [LICENSE.txt](LICENSE.txt)

Media is **not** fetched from RedGIFs in this process. A separate Gluetun stack
on docker-svr writes files into subdirectories of the shared drop folder
(default host `/home/james/vault/redgifs`). UBETRA bind-mounts that tree
read-only.

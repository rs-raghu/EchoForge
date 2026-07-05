# Renderer Stage 2 WebEditor v2

This replaces the first simple editor UI with a more video-editor-like layout:

- media bin
- program monitor
- transport controls
- custom timeline with playhead
- clip list
- inspector
- drag lyric position
- save back to `editor/editor_project.json`

Important fix: the server now supports HTTP `Range` requests for audio, so browser seeking works correctly.

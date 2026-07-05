# Renderer Stage 1: Editor Project

This stage prepares a clean editable timeline for WebEditor/rendering.

Inputs:

- `audio/source_audio.m4a`
- `images/video_background.jpg`
- `sync/final_synced_lyrics.lrc`
- optional `sync/final_synced_lyrics.json`

Outputs:

- `editor/editor_project.json`
- `editor/timeline.json`
- `editor/preview.html`
- `editor/prepare_report.json`

Run:

```bat
python scripts\prepare_editor_project.py --project "projects\0001_dai-dai_shakira-and-burna-boy" --force
```

Then open:

```text
projects\0001_dai-dai_shakira-and-burna-boy\editor\preview.html
```

This is only the bridge. Final render/export comes after the editor project is verified.

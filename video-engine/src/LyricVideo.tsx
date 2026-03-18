import React from 'react';
import {
  AbsoluteFill,
  Audio,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
  Img,
  Sequence,
} from 'remotion';
import timestamps from '../public/timestamps.json';
import metadata from '../public/metadata.json';
import audioConfig from '../public/audioConfig.json';
import { loadFont } from '@remotion/google-fonts/Inter';

// ─── Load Inter from Google Fonts ────────────────────────────────────────────
// loadFont() must be called at module level (outside the component) so Remotion
// can resolve and embed the font before rendering begins.
// The returned fontFamily string is used in every text style below.
const { fontFamily } = loadFont();

// ─── Timeline constants ───────────────────────────────────────────────────────
const LOGO_START    = 0.0;   // seconds
const LOGO_END      = 2.0;
const DETAILS_START = 2.0;
const DETAILS_END   = 5.0;
const LYRICS_START  = 5.0;
const FADE_S        = 0.5;   // fade in / out duration (seconds)

// ─── Lyric pre-roll: show the line 0.2 s before it starts ────────────────────
const OFFSET = 0.2;

export const LyricVideo: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps;

  // audioDelayInVideo: how many seconds into the video the audio track starts.
  // render_engine.py writes this value into audioConfig.json.
  // When first lyric >= 5 s  →  delay = 0  (song starts at frame 0).
  // When first lyric <  5 s  →  delay > 0  (song starts later so lyrics
  //                              land exactly when the details screen ends).
  const audioDelayInVideo: number = audioConfig.audioDelayInVideo;

  // songTime: position inside the audio track that corresponds to this video frame.
  const songTime = Math.max(0, currentTime - audioDelayInVideo);

  // ── Phase flags ─────────────────────────────────────────────────────────────
  const inLogoPhase    = currentTime <  LOGO_END;
  const inDetailsPhase = currentTime >= DETAILS_START && currentTime < DETAILS_END;
  const inLyricsPhase  = currentTime >= LYRICS_START;

  // ── Logo opacity: fade in over FADE_S, hold, fade out over FADE_S ───────────
  const fadeFr = FADE_S * fps;
  const logoOpacity = interpolate(
    frame,
    [
      LOGO_START * fps,
      LOGO_START * fps + fadeFr,
      LOGO_END   * fps - fadeFr,
      LOGO_END   * fps,
    ],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
  );

  // ── Details opacity: same fade pattern ──────────────────────────────────────
  const detailsOpacity = interpolate(
    frame,
    [
      DETAILS_START * fps,
      DETAILS_START * fps + fadeFr,
      DETAILS_END   * fps - fadeFr,
      DETAILS_END   * fps,
    ],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
  );

  // ── Active lyric line (matched against song-relative time) ──────────────────
  const currentLineData = timestamps.segments.find(
    (s: { start: number; end: number; text: string }) =>
      songTime >= s.start - OFFSET && songTime <= s.end,
  );

  // ── Lyric enter animation ────────────────────────────────────────────────────
  // lineStartFrame is in VIDEO frame space (add audioDelayInVideo back)
  const lineStartFrame = currentLineData
    ? (currentLineData.start - OFFSET + audioDelayInVideo) * fps
    : 0;
  const frameRelativeToLine = currentLineData ? frame - lineStartFrame : 0;

  const slideAnimation = spring({
    fps,
    frame: frameRelativeToLine,
    config: { damping: 14, stiffness: 100 },
    durationInFrames: 20,
  });
  const yOffset = interpolate(slideAnimation, [0, 1], [40, 0]);

  // ── Lyric opacity: fade in then fade out within the line's duration ──────────
  const rawDuration      = currentLineData
    ? (currentLineData.end - currentLineData.start) * fps
    : 0;
  const lineDurationFr   = Math.max(1, rawDuration);
  const safeFade         = Math.max(0.001, Math.min(10, lineDurationFr * 0.49));
  const lyricOpacity     = currentLineData
    ? interpolate(
        frameRelativeToLine,
        [0, safeFade, lineDurationFr - safeFade, lineDurationFr],
        [0, 1, 1, 0],
        { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
      )
    : 0;

  // ─────────────────────────────────────────────────────────────────────────────
  return (
    <AbsoluteFill
      style={{
        justifyContent: 'center',
        alignItems: 'center',
        padding: '0 10%',
        backgroundColor: '#000',
      }}
    >
      {/* ── Always-on background ─────────────────────────────────────────────── */}
      <Img
        src={staticFile('bg.jpg')}
        style={{
          position: 'absolute',
          width: '100%',
          height: '100%',
          objectFit: 'cover',
        }}
      />
      {/* Dark scrim */}
      <div
        style={{
          position: 'absolute',
          width: '100%',
          height: '100%',
          backgroundColor: 'rgba(0,0,0,0.6)',
        }}
      />

      {/* ── Audio — delayed to align first lyric with the 5 s mark ─────────────
           Sequence.from is in frames; when delay=0 it starts at frame 0.        */}
      <Sequence from={Math.round(audioDelayInVideo * fps)}>
        <Audio src={staticFile('audio.mp3')} />
      </Sequence>

      {/* ── PHASE 1 · Logo (0 s – 2 s) ─────────────────────────────────────── */}
      {inLogoPhase && (
        <Img
          src={staticFile('logo.png')}
          // onError={() => setLogoAvailable(false)}
          style={{
            width: '320px',
            opacity: logoOpacity,
            zIndex: 10,
          }}
        />
      )}

      {/* ── PHASE 2 · Song details (2 s – 5 s) ────────────────────────────── */}
      {inDetailsPhase && (
        <div
          style={{
            textAlign: 'center',
            zIndex: 10,
            opacity: detailsOpacity,
            padding: '0 8%',
          }}
        >
          <h1
            style={{
              color: '#ffffff',
              fontSize: '100px',
              fontWeight: 'bold',
              margin: 0,
              fontFamily,
              letterSpacing: '-2px',
              lineHeight: 1.1,
            }}
          >
            {metadata.title}
          </h1>
          <h2
            style={{
              color: '#b3b3b3',
              fontSize: '55px',
              margin: '24px 0 0 0',
              fontFamily,
              fontWeight: 'normal',
            }}
          >
            {metadata.artist}
          </h2>
        </div>
      )}

      {/* ── PHASE 3 · Synced lyrics (5 s +) ────────────────────────────────── */}
      {inLyricsPhase && currentLineData && (
        <h1
          style={{
            color: '#ffffff',
            fontSize: '85px',
            fontFamily,
            fontWeight: 800,
            textAlign: 'center',
            transform: `translateY(${yOffset}px)`,
            opacity: lyricOpacity,
            lineHeight: 1.3,
            margin: 0,
            zIndex: 10,
          }}
        >
          {currentLineData.text.trim()}
        </h1>
      )}
    </AbsoluteFill>
  );
};
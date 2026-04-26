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
import fontConfig from '../public/fontConfig.json';

// ─── TypeScript types ─────────────────────────────────────────────────────────
interface WordTimestamp {
  word:  string;
  start: number;
  end:   number;
}

interface Segment {
  text:   string;
  start:  number;
  end:    number;
  words?: WordTimestamp[];
}

interface FontConfig {
  titleFont?:  string;   // CSS font-family or "custom"
  artistFont?: string;
  lyricsFont?: string;
  titleFontFile?:  string;   // relative URL under /public/fonts/
  artistFontFile?: string;
  lyricsFontFile?: string;
}

const typedSegments = (timestamps as { segments: Segment[] }).segments;
const fc = fontConfig as FontConfig;

// ─── Dynamic font-face injection ─────────────────────────────────────────────
// If the render engine staged custom .ttf files into public/fonts/, we inject
// @font-face rules so the browser inside Remotion's renderer can find them.
const _injectFontFaces = (() => {
  const rules: string[] = [];
  if (fc.lyricsFontFile) {
    rules.push(`
      @font-face {
        font-family: 'CustomLyrics';
        src: url('${staticFile(`fonts/${fc.lyricsFontFile}`)}') format('truetype');
      }
    `);
  }
  if (fc.titleFontFile) {
    rules.push(`
      @font-face {
        font-family: 'CustomTitle';
        src: url('${staticFile(`fonts/${fc.titleFontFile}`)}') format('truetype');
      }
    `);
  }
  if (fc.artistFontFile) {
    rules.push(`
      @font-face {
        font-family: 'CustomArtist';
        src: url('${staticFile(`fonts/${fc.artistFontFile}`)}') format('truetype');
      }
    `);
  }
  return rules.join('\n');
})();

// ─── Font families used in styles ─────────────────────────────────────────────
const LYRICS_FAMILY  = fc.lyricsFontFile  ? 'CustomLyrics, sans-serif'
                     : fc.lyricsFont       ? `${fc.lyricsFont}, sans-serif`
                     : 'Inter, sans-serif';

const TITLE_FAMILY   = fc.titleFontFile   ? 'CustomTitle, sans-serif'
                     : fc.titleFont        ? `${fc.titleFont}, sans-serif`
                     : 'Inter, sans-serif';

const ARTIST_FAMILY  = fc.artistFontFile  ? 'CustomArtist, sans-serif'
                     : fc.artistFont       ? `${fc.artistFont}, sans-serif`
                     : 'Inter, sans-serif';

// ─── Timeline constants ───────────────────────────────────────────────────────
const LOGO_START    = 0.0;
const LOGO_END      = 2.0;
const DETAILS_START = 2.0;
const DETAILS_END   = 5.0;
const LYRICS_START  = 5.0;
const FADE_S        = 0.5;
const OFFSET        = 0.2;   // lyric pre-roll (seconds)

// ─── 3-Line scrolling layout ──────────────────────────────────────────────────
// The three lines scroll vertically as a unit:
//   PREV  — faded / smaller  (above)
//   CURR  — bright / larger  (centre)
//   NEXT  — faded / smaller  (below)

const LINE_HEIGHT_CURR = 110;   // px — current line
const LINE_HEIGHT_SIDE = 80;    // px — prev / next line
const LINE_GAP         = 20;    // px — gap between lines

// Total scroll window height (used for translateY calculation)
const WINDOW_H = LINE_HEIGHT_SIDE + LINE_GAP + LINE_HEIGHT_CURR + LINE_GAP + LINE_HEIGHT_SIDE;

// ─── Karaoke highlight colours ────────────────────────────────────────────────
const COLOR_FUTURE  = 'rgba(255,255,255,0.30)';
const COLOR_ACTIVE  = '#FFD700';
const COLOR_PAST    = '#ffffff';
const COLOR_SIDE    = 'rgba(255,255,255,0.45)';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function findLineIndex(songTime: number): number {
  // Return the index of the currently active segment, or -1 if none.
  for (let i = 0; i < typedSegments.length; i++) {
    const s = typedSegments[i];
    if (songTime >= s.start - OFFSET && songTime <= s.end) {
      return i;
    }
  }
  // Between lines — return index of next upcoming segment
  for (let i = 0; i < typedSegments.length; i++) {
    if (typedSegments[i].start - OFFSET > songTime) {
      return Math.max(0, i - 1);
    }
  }
  return typedSegments.length - 1;
}

function renderKaraoke(segment: Segment, songTime: number): React.ReactNode {
  if (!segment.words || segment.words.length === 0) {
    return <span style={{ color: COLOR_PAST }}>{segment.text.trim()}</span>;
  }
  return segment.words.map((w, i) => {
    let color: string;
    if (songTime > w.end)       color = COLOR_PAST;
    else if (songTime >= w.start) color = COLOR_ACTIVE;
    else                          color = COLOR_FUTURE;
    const gap = i < segment.words!.length - 1 ? '\u00a0' : '';
    return (
      <span key={i} style={{ color, transition: 'color 0.08s linear' }}>
        {w.word}{gap}
      </span>
    );
  });
}

// ─── Individual scrolling line component ──────────────────────────────────────

interface LineProps {
  segment:  Segment;
  role:     'prev' | 'curr' | 'next';
  songTime: number;
}

const ScrollLine: React.FC<LineProps> = ({ segment, role, songTime }) => {
  const isCurr     = role === 'curr';
  const fontSize   = isCurr ? LINE_HEIGHT_CURR   : LINE_HEIGHT_SIDE;
  const opacity    = isCurr ? 1                  : 0.38;
  const fontWeight = isCurr ? 800                : 500;
  const scale      = isCurr ? 1                  : 0.82;

  return (
    <div
      style={{
        height:         fontSize,
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'center',
        opacity,
        transform:      `scale(${scale})`,
        transition:     'opacity 0.35s ease, transform 0.35s ease',
        overflow:       'hidden',
        width:          '100%',
      }}
    >
      <span
        style={{
          fontSize:      `${fontSize * 0.75}px`,
          fontFamily:    LYRICS_FAMILY,
          fontWeight,
          textAlign:     'center',
          lineHeight:    1.25,
          color:         isCurr ? undefined : COLOR_SIDE,
        }}
      >
        {isCurr ? renderKaraoke(segment, songTime) : segment.text.trim()}
      </span>
    </div>
  );
};


// ─── Main component ───────────────────────────────────────────────────────────

export const LyricVideo: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime     = frame / fps;
  const audioDelayInVideo: number = audioConfig.audioDelayInVideo;
  const songTime        = Math.max(0, currentTime - audioDelayInVideo);

  // ── Phase flags ──────────────────────────────────────────────────────────────
  const inLogoPhase    = currentTime <  LOGO_END;
  const inDetailsPhase = currentTime >= DETAILS_START && currentTime < DETAILS_END;
  const inLyricsPhase  = currentTime >= LYRICS_START;

  // ── Intro opacity helpers ─────────────────────────────────────────────────
  const fadeFr = FADE_S * fps;

  const logoOpacity = interpolate(
    frame,
    [LOGO_START * fps, LOGO_START * fps + fadeFr, LOGO_END * fps - fadeFr, LOGO_END * fps],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
  );

  const detailsOpacity = interpolate(
    frame,
    [DETAILS_START * fps, DETAILS_START * fps + fadeFr, DETAILS_END * fps - fadeFr, DETAILS_END * fps],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
  );

  // ── 3-line scrolling window ───────────────────────────────────────────────
  const currIdx  = findLineIndex(songTime);
  const prevSeg  = currIdx > 0                          ? typedSegments[currIdx - 1] : null;
  const currSeg  = typedSegments[currIdx]               ?? null;
  const nextSeg  = currIdx < typedSegments.length - 1  ? typedSegments[currIdx + 1] : null;

  // Smooth scroll: spring-driven translateY from current → next transition.
  // Each time currIdx advances, the spring resets and scrolls upward.
  const lineEnterFrame = currSeg
    ? (currSeg.start - OFFSET + audioDelayInVideo) * fps
    : 0;
  const frameInLine = frame - lineEnterFrame;

  const scrollSpring = spring({
    fps,
    frame: Math.max(0, frameInLine),
    config: { damping: 18, stiffness: 90 },
    durationInFrames: 18,
  });

  // scrollY: when a new line starts, content scrolls up by one LINE_HEIGHT_SIDE + LINE_GAP
  const scrollY = interpolate(scrollSpring, [0, 1], [LINE_HEIGHT_SIDE + LINE_GAP, 0]);

  // Overall lyric block opacity: fade in at LYRICS_START
  const lyricsBlockOpacity = interpolate(
    frame,
    [LYRICS_START * fps, LYRICS_START * fps + fadeFr],
    [0, 1],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' },
  );

  return (
    <AbsoluteFill
      style={{ justifyContent: 'center', alignItems: 'center', backgroundColor: '#000' }}
    >
      {/* Inject custom font-face declarations */}
      {_injectFontFaces && (
        <style dangerouslySetInnerHTML={{ __html: _injectFontFaces }} />
      )}

      {/* Background image */}
      <Img
        src={staticFile('bg.jpg')}
        style={{
          position: 'absolute', width: '100%', height: '100%', objectFit: 'cover',
        }}
      />

      {/* Dark scrim */}
      <div
        style={{
          position: 'absolute', width: '100%', height: '100%',
          backgroundColor: 'rgba(0,0,0,0.62)',
        }}
      />

      {/* Audio — delayed so first lyric aligns with intro end */}
      <Sequence from={Math.round(audioDelayInVideo * fps)}>
        <Audio src={staticFile('audio.mp3')} />
      </Sequence>

      {/* ── PHASE 1: Logo ──────────────────────────────────────────────────── */}
      {inLogoPhase && (
        <Img
          src={staticFile('logo.png')}
          style={{ width: '320px', opacity: logoOpacity, zIndex: 10 }}
        />
      )}

      {/* ── PHASE 2: Song details ─────────────────────────────────────────── */}
      {inDetailsPhase && (
        <div
          style={{
            textAlign: 'center', zIndex: 10, opacity: detailsOpacity, padding: '0 8%',
          }}
        >
          <h1
            style={{
              color: '#fff', fontSize: '100px', fontWeight: 'bold',
              margin: 0, fontFamily: TITLE_FAMILY,
              letterSpacing: '-2px', lineHeight: 1.1,
            }}
          >
            {metadata.title}
          </h1>
          <h2
            style={{
              color: '#b3b3b3', fontSize: '55px', margin: '24px 0 0 0',
              fontFamily: ARTIST_FAMILY, fontWeight: 'normal',
            }}
          >
            {metadata.artist}
          </h2>
        </div>
      )}

      {/* ── PHASE 3: 3-Line scrolling karaoke ────────────────────────────── */}
      {inLyricsPhase && currSeg && (
        <div
          style={{
            position:   'absolute',
            left:       '10%',
            right:      '10%',
            top:        '50%',
            transform:  `translateY(calc(-50% + ${scrollY}px))`,
            opacity:    lyricsBlockOpacity,
            zIndex:     10,
            display:    'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap:        `${LINE_GAP}px`,
          }}
        >
          {/* Previous line */}
          {prevSeg && (
            <ScrollLine segment={prevSeg} role="prev" songTime={songTime} />
          )}
          {!prevSeg && (
            <div style={{ height: LINE_HEIGHT_SIDE }} />
          )}

          {/* Current line */}
          <ScrollLine segment={currSeg} role="curr" songTime={songTime} />

          {/* Next line */}
          {nextSeg && (
            <ScrollLine segment={nextSeg} role="next" songTime={songTime} />
          )}
          {!nextSeg && (
            <div style={{ height: LINE_HEIGHT_SIDE }} />
          )}
        </div>
      )}
    </AbsoluteFill>
  );
};
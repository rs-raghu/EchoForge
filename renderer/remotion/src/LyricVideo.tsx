import React, { useState, useEffect } from 'react';
import { AbsoluteFill, Audio, interpolate, Sequence, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';

interface Word {
  word: string;
  start: number;
  end: number;
}

interface Segment {
  start: number;
  end: number;
  text: string;
  words: Word[];
}

export interface LyricVideoProps {
  title: string;
  artist: string;
  audioUrl: string;
  timestampsUrl: string;
}

const useTimestamps = (url: string): { segments: Segment[] } | null => {
  const [data, setData] = useState<{ segments: Segment[] } | null>(null);

  useEffect(() => {
    if (!url) {
      setData({ segments: [] });
      return;
    }

    fetch(staticFile(url))
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Failed to load timestamps: ${res.status} ${res.statusText}`);
        }
        return res.json();
      })
      .then((json) => {
        const segments = Array.isArray(json?.segments) ? json.segments : [];
        setData({ segments });
      })
      .catch((err) => {
        console.error('Error fetching timestamps:', err);
        setData({ segments: [] });
      });
  }, [url]);

  return data;
};

export const LyricVideo: React.FC<LyricVideoProps> = ({
  title,
  artist,
  audioUrl,
  timestampsUrl,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const lyricsData = useTimestamps(timestampsUrl);

  const LOGO_DURATION_FRAMES = 2 * fps;
  const DETAILS_DURATION_FRAMES = 3 * fps;
  const LYRICS_START_FRAME = LOGO_DURATION_FRAMES + DETAILS_DURATION_FRAMES;

  const logoOpacity = interpolate(
    frame,
    [0, LOGO_DURATION_FRAMES / 2, LOGO_DURATION_FRAMES - 10, LOGO_DURATION_FRAMES],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  const detailsOpacity = interpolate(
    frame,
    [
      LOGO_DURATION_FRAMES,
      LOGO_DURATION_FRAMES + 15,
      LYRICS_START_FRAME - 15,
      LYRICS_START_FRAME,
    ],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  if (!lyricsData) {
    return <AbsoluteFill style={{ backgroundColor: 'black' }} />;
  }

  const { segments } = lyricsData;
  const hasSegments = segments.length > 0;

  const currentTime = frame / fps;
  const currentSegmentIndex = segments.findIndex((segment) => {
    return currentTime >= segment.start && currentTime <= segment.end;
  });

  const activeSegment = segments[currentSegmentIndex];

  const renderWords = (segment: Segment) => {
    if (!segment.words || segment.words.length === 0) {
      return segment.text;
    }

    return segment.words.map((w, idx) => {
      const wordStartFrame = w.start * fps;
      const wordEndFrame = w.end * fps;
      const isWordActive = frame >= wordStartFrame && frame <= wordEndFrame;
      const isWordPassed = frame > wordEndFrame;

      let color = 'inherit';
      if (isWordActive) color = '#FFD700';
      else if (isWordPassed) color = '#aaa';

      const needsSpace = !w.word.trim().endsWith('-');

      return (
        <span key={idx}>
          <span style={{ color }}>{w.word}</span>
          {needsSpace && ' '}
        </span>
      );
    });
  };

  return (
    <AbsoluteFill style={{ backgroundColor: '#111', color: 'white', fontFamily: 'sans-serif' }}>
      {audioUrl ? <Audio src={staticFile(audioUrl)} /> : null}

      <Sequence from={0} durationInFrames={LOGO_DURATION_FRAMES}>
        <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', opacity: logoOpacity }}>
          <div style={{ fontSize: 80, fontWeight: 'bold', color: '#FFD700' }}>
            EchoForge
          </div>
        </AbsoluteFill>
      </Sequence>

      <Sequence from={LOGO_DURATION_FRAMES} durationInFrames={DETAILS_DURATION_FRAMES}>
        <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', opacity: detailsOpacity }}>
          <div style={{ fontSize: 72, fontWeight: 'bold', marginBottom: 24, maxWidth: '82%', textAlign: 'center' }}>{title}</div>
          <div style={{ fontSize: 42, color: '#ccc', maxWidth: '82%', textAlign: 'center' }}>{artist}</div>
        </AbsoluteFill>
      </Sequence>

      <Sequence from={LYRICS_START_FRAME} durationInFrames={durationInFrames - LYRICS_START_FRAME}>
        <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', padding: '0 12%' }}>
          <div style={{ width: '100%', minHeight: 120, textAlign: 'center' }}>
            
            {hasSegments ? (
              <div style={{ fontSize: 74, fontWeight: 800, color: 'white', lineHeight: 1.18 }}>
                {activeSegment ? renderWords(activeSegment) : ''}
              </div>
            ) : (
              <div style={{ fontSize: 48, color: '#777', minHeight: '80px', textAlign: 'center' }}>
                No lyrics available
              </div>
            )}

          </div>
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};

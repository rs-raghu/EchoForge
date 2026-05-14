import React, { useState, useEffect } from 'react';

// --- REMOTION MOCKS FOR PREVIEW ---
// The preview environment cannot resolve the 'remotion' package.
// We mock its core components here for the preview to work.
// When running locally, replace this block with:
// import { AbsoluteFill, Audio, interpolate, Sequence, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';

export const AbsoluteFill: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ style, ...props }) => (
  <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', ...style }} {...props} />
);

export const Audio: React.FC<{ src: string }> = ({ src }) => <audio src={src} autoPlay />;

export const Sequence: React.FC<{ from: number; durationInFrames?: number; children: React.ReactNode }> = ({ from, durationInFrames, children }) => {
  const frame = useCurrentFrame();
  const isVisible = frame >= from && (durationInFrames === undefined || frame < from + durationInFrames);
  return isVisible ? <>{children}</> : null;
};

export const interpolate = (input: number, inputRange: number[], outputRange: number[], options?: any) => {
  if (input <= inputRange[0]) return outputRange[0];
  if (input >= inputRange[inputRange.length - 1]) return outputRange[outputRange.length - 1];
  for (let i = 0; i < inputRange.length - 1; i++) {
    if (input >= inputRange[i] && input <= inputRange[i + 1]) {
       const progress = (input - inputRange[i]) / (inputRange[i + 1] - inputRange[i]);
       return outputRange[i] + progress * (outputRange[i + 1] - outputRange[i]);
    }
  }
  return outputRange[0];
};

export const staticFile = (path: string) => path;

// Simulate a running frame counter for the preview at 30fps
let globalFrame = 0;
const frameListeners: Set<Function> = new Set();
setInterval(() => {
  globalFrame++;
  frameListeners.forEach(fn => fn(globalFrame));
}, 1000 / 30);

export const useCurrentFrame = () => {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    const handler = (f: number) => setFrame(f);
    frameListeners.add(handler);
    return () => { frameListeners.delete(handler); }
  }, []);
  return frame;
};

export const useVideoConfig = () => ({ fps: 30, durationInFrames: 3000 });
// --- END REMOTION MOCKS ---

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
  const [data, setData] = React.useState<{ segments: Segment[] } | null>(null);

  React.useEffect(() => {
    fetch(staticFile(url))
      .then((res) => res.json())
      .then((json) => setData(json))
      .catch((err) => {
        console.error('Error fetching timestamps:', err);
        // Fallback mock data so the preview doesn't stay black
        setData({
          segments: [
            { start: 0, end: 3, text: "Simulated Preview Line 1", words: [{word: "Simulated", start: 0, end: 1}, {word: "Preview", start: 1, end: 2}, {word: "Line 1", start: 2, end: 3}] },
            { start: 3, end: 6, text: "Please use actual environment for full render", words: [{word: "Please", start: 3, end: 3.5}, {word: "use", start: 3.5, end: 4}, {word: "actual", start: 4, end: 5}, {word: "environment", start: 5, end: 6}] }
          ]
        });
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

  const currentSegmentIndex = segments.findIndex((segment) => {
    const startFrame = segment.start * fps;
    const endFrame = segment.end * fps;
    return frame >= startFrame && frame <= endFrame;
  });

  const activeSegment = segments[currentSegmentIndex];
  const previousSegment = segments[currentSegmentIndex - 1];
  const nextSegment = segments[currentSegmentIndex + 1];

  return (
    <AbsoluteFill style={{ backgroundColor: '#111', color: 'white', fontFamily: 'sans-serif' }}>
      <Audio src={staticFile(audioUrl)} />

      <Sequence from={0} durationInFrames={LOGO_DURATION_FRAMES}>
        <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', opacity: logoOpacity }}>
          <div style={{ fontSize: 80, fontWeight: 'bold', color: '#FFD700' }}>
            EchoForge
          </div>
        </AbsoluteFill>
      </Sequence>

      <Sequence from={LOGO_DURATION_FRAMES} durationInFrames={DETAILS_DURATION_FRAMES}>
        <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', opacity: detailsOpacity }}>
          <div style={{ fontSize: 60, fontWeight: 'bold', marginBottom: 20 }}>{title}</div>
          <div style={{ fontSize: 40, color: '#ccc' }}>{artist}</div>
        </AbsoluteFill>
      </Sequence>

      <Sequence from={LYRICS_START_FRAME} durationInFrames={durationInFrames - LYRICS_START_FRAME}>
        <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', padding: '0 10%' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '30px', textAlign: 'center', width: '100%' }}>
            
            <div style={{ fontSize: 40, color: '#666', minHeight: '50px', opacity: 0.5, transition: 'all 0.3s' }}>
              {previousSegment ? previousSegment.text : ''}
            </div>

            <div style={{ fontSize: 60, fontWeight: 'bold', color: 'white', minHeight: '80px', display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: '15px' }}>
              {activeSegment ? (
                 activeSegment.words && activeSegment.words.length > 0 ? (
                    activeSegment.words.map((w, idx) => {
                        const wordStartFrame = w.start * fps;
                        const wordEndFrame = w.end * fps;
                        const isWordActive = frame >= wordStartFrame && frame <= wordEndFrame;
                        const isWordPassed = frame > wordEndFrame;

                        let color = 'white';
                        if (isWordActive) color = '#FFD700';
                        else if (isWordPassed) color = '#aaa';

                        return (
                            <span key={idx} style={{ color, transition: 'color 0.1s' }}>
                                {w.word}
                            </span>
                        );
                    })
                 ) : (
                     <span>{activeSegment.text}</span>
                 )
              ) : (
                 <span style={{ color: '#333' }}>...</span>
              )}
            </div>

            <div style={{ fontSize: 40, color: '#666', minHeight: '50px', opacity: 0.5 }}>
              {nextSegment ? nextSegment.text : ''}
            </div>

          </div>
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};

// Main App component required for the preview environment
export default function App() {
  return (
    <LyricVideo 
      title="Preview Title" 
      artist="Preview Artist" 
      audioUrl="audio.mp3" 
      timestampsUrl="timestamps.json" 
    />
  );
}
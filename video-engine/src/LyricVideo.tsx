import React from 'react';
import { 
  AbsoluteFill, 
  Audio, 
  staticFile, 
  useCurrentFrame, 
  useVideoConfig, 
  spring, 
  interpolate 
} from 'remotion';
import timestamps from '../public/timestamps.json';
import metadata from '../public/metadata.json';

export const LyricVideo: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps;

  // 1. Instead of flattening words, we just search the main "segments" (full lines)
  const currentLineData = timestamps.segments.find(
    (s: any) => currentTime >= s.start && currentTime <= s.end
  );

  // --- PHYSICS & ANIMATION ---
  const lineStartFrame = currentLineData ? currentLineData.start * fps : 0;
  const frameRelativeToLine = currentLineData ? frame - lineStartFrame : 0;

  // Create a smooth "slide up" effect for the text
  const slideAnimation = spring({
    fps,
    frame: frameRelativeToLine,
    config: { damping: 14, stiffness: 100 }, // Slower, elegant slide
    durationInFrames: 20,
  });

  // Map the spring value to physical pixels (Starts 40px down, slides to 0)
  const yOffset = interpolate(slideAnimation, [0, 1], [40, 0]);

  // Fade the line in over 10 frames, and fade it out 10 frames before it ends
  const lineDurationFrames = currentLineData ? (currentLineData.end - currentLineData.start) * fps : 0;
  const safeFade = Math.max(0.1, Math.min(10, lineDurationFrames * 0.4));
  const opacity = currentLineData ? interpolate(
    frameRelativeToLine,
    [0, safeFade, lineDurationFrames - safeFade, lineDurationFrames], 
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  ) : 0;

  return (
    <AbsoluteFill style={{ 
      background: 'linear-gradient(to bottom, #1a1a2e, #16213e, #0f3460)', 
      justifyContent: 'center', 
      alignItems: 'center',
      padding: '0 10%' // Keeps long lines from touching the edges of the screen
    }}>
      
      <Audio src={staticFile('audio.mp3')} />

      {/* The Dynamic Line-by-Line Lyric */}
      {currentLineData && (
        <h1 style={{ 
          color: '#ffffff', 
          fontSize: '85px', // Shrunk down to fit horizontal screens
          fontFamily: 'sans-serif',
          fontWeight: 800,
          textAlign: 'center',
          textShadow: '0px 0px 20px rgba(255, 255, 255, 0.3)',
          transform: `translateY(${yOffset}px)`,
          opacity: opacity,
          lineHeight: '1.3',
          margin: 0
        }}>
          {currentLineData.text.trim()}
        </h1>
      )}

      {/* The Now Playing Footer */}
      <div style={{ position: 'absolute', bottom: 80, textAlign: 'center' }}>
        <h2 style={{ 
          color: '#e94560', 
          fontSize: '40px', 
          margin: 0, 
          fontFamily: 'sans-serif',
          fontWeight: 'bold',
          textTransform: 'uppercase',
          letterSpacing: '5px'
        }}>
          {metadata.title}
        </h2>
        <h3 style={{ 
          color: '#a0a0a0', 
          fontSize: '25px', 
          margin: '10px 0 0 0', 
          fontFamily: 'sans-serif',
          fontWeight: 'normal'
        }}>
          {metadata.artist}
        </h3>
      </div>
      
    </AbsoluteFill>
  );
};
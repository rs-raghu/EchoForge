import React from 'react';
import { 
  AbsoluteFill, 
  Audio, 
  staticFile, 
  useCurrentFrame, 
  useVideoConfig, 
  spring, 
  interpolate,
  Img 
} from 'remotion';
import timestamps from '../public/timestamps.json';
import metadata from '../public/metadata.json';

export const LyricVideo: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps;

  // --- TIMELINE SEQUENCING ---
  const showCover = currentTime < 2.0; 
  const showDetails = currentTime >= 2.0 && currentTime < 5.0;
  const showLyrics = currentTime >= 5.0;

  // --- THE 0.2s PRE-ROLL OFFSET ---
  const OFFSET = 0.2;
  
  const currentLineData = timestamps.segments.find(
    (s: any) => currentTime >= (s.start - OFFSET) && currentTime <= s.end
  );

  // --- PHYSICS ---
  const lineStartFrame = currentLineData ? (currentLineData.start - OFFSET) * fps : 0;
  const frameRelativeToLine = currentLineData ? frame - lineStartFrame : 0;

  const slideAnimation = spring({
    fps,
    frame: frameRelativeToLine,
    config: { damping: 14, stiffness: 100 },
    durationInFrames: 20,
  });

  const yOffset = interpolate(slideAnimation, [0, 1], [40, 0]);

  const rawDuration = currentLineData ? (currentLineData.end - currentLineData.start) * fps : 0;
  const lineDurationFrames = Math.max(1, rawDuration);
  const safeFade = Math.max(0.001, Math.min(10, lineDurationFrames * 0.49));

  const opacity = currentLineData ? interpolate(
    frameRelativeToLine,
    [0, safeFade, lineDurationFrames - safeFade, lineDurationFrames], 
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  ) : 0;

  return (
    <AbsoluteFill style={{ 
      justifyContent: 'center', 
      alignItems: 'center',
      padding: '0 10%',
      backgroundColor: '#000'
    }}>
      
      {/* PHASE 0: Dynamic Background with Dark Overlay */}
      <Img 
        src={staticFile('bg.jpg')} 
        style={{ position: 'absolute', width: '100%', height: '100%', objectFit: 'cover' }} 
      />
      <div style={{ position: 'absolute', width: '100%', height: '100%', backgroundColor: 'rgba(0,0,0,0.6)' }} />

      <Audio src={staticFile('audio.mp3')} />

      {/* PHASE 1: The Intro Image (0s - 2s) */}
      {showCover && (
        <Img 
          src={staticFile('cover.jpg')} 
          style={{ 
            width: '600px', 
            height: '600px', 
            borderRadius: '20px', 
            boxShadow: '0 20px 60px rgba(0,0,0,0.8)',
            zIndex: 10
          }} 
        />
      )}

      {/* PHASE 2: The Track Details (2s - 5s) */}
      {showDetails && (
        <div style={{ textAlign: 'center', zIndex: 10 }}>
          <h1 style={{ 
            color: '#ffffff', fontSize: '120px', fontWeight: 'bold', 
            margin: 0, fontFamily: 'sans-serif', letterSpacing: '-2px'
          }}>
            {metadata.title}
          </h1>
          <h2 style={{ 
            color: '#b3b3b3', fontSize: '60px', margin: '20px 0 0 0', 
            fontFamily: 'sans-serif', fontWeight: 'normal'
          }}>
            {metadata.artist}
          </h2>
        </div>
      )}

      {/* PHASE 3: The Synced Lyrics (>5s) */}
      {showLyrics && currentLineData && (
        <h1 style={{ 
          color: '#ffffff', 
          fontSize: '85px', 
          fontFamily: 'sans-serif',
          fontWeight: 800,
          textAlign: 'center',
          transform: `translateY(${yOffset}px)`,
          opacity: opacity,
          lineHeight: '1.3',
          margin: 0,
          zIndex: 10
        }}>
          {currentLineData.text.trim()}
        </h1>
      )}
      
    </AbsoluteFill>
  );
};
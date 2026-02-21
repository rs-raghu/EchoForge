import React from 'react';
import { Composition } from 'remotion';
import { LyricVideo } from './LyricVideo';
import timestamps from '../public/timestamps.json';

// --- DYNAMIC DURATION CALCULATION ---
// Look at the very last line/segment in the song
const lastSegment = timestamps.segments[timestamps.segments.length - 1];

// Fallback to 10 seconds, otherwise use the final timestamp + 2 seconds buffer
const videoDurationInSeconds = lastSegment ? lastSegment.end + 2 : 10; 
const FPS = 30;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="EchoForgeLyricVideo"
        component={LyricVideo}
        durationInFrames={Math.ceil(videoDurationInSeconds * FPS)}
        fps={FPS}
        width={1920}  // 16:9 Landscape Width
        height={1080} // 16:9 Landscape Height
      />
    </>
  );
};
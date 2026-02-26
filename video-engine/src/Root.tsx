import React from 'react';
import { Composition } from 'remotion';
import { LyricVideo } from './LyricVideo';
import timestamps from '../public/timestamps.json';
import audioConfig from '../public/audioConfig.json';

// ─── Dynamic duration ─────────────────────────────────────────────────────────
// Total video length = audio delay (intro padding) + song end + 2 s buffer.
//
// audioDelayInVideo = 0  → song plays from frame 0, video ends at lastSegment.end + 2
// audioDelayInVideo = N  → song starts N seconds in, video ends at N + lastSegment.end + 2
//
const lastSegment       = timestamps.segments[timestamps.segments.length - 1];
const audioDelayInVideo = audioConfig.audioDelayInVideo;
const songEndSeconds    = lastSegment ? lastSegment.end : 10;

const videoDurationInSeconds = audioDelayInVideo + songEndSeconds + 2;
const FPS = 30;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="EchoForgeLyricVideo"
        component={LyricVideo}
        durationInFrames={Math.ceil(videoDurationInSeconds * FPS)}
        fps={FPS}
        width={1920}
        height={1080}
      />
    </>
  );
};
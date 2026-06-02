import React from 'react';
import { Composition, getInputProps } from 'remotion';
import { LyricVideo, LyricVideoProps } from './LyricVideo';

export const RemotionRoot: React.FC = () => {
  // getInputProps reads the dynamic props passed from the Python worker
  const passedProps = getInputProps();

  // Explicitly typing the default props ensures they match the LyricVideoProps interface
  const defaultProps: LyricVideoProps = {
    title: 'Test Track',
    artist: 'EchoForge Band',
    audioUrl: '',
    timestampsUrl: '',
  };

  // Merge passed props with defaults and cast to the correct interface
  const props = { ...defaultProps, ...passedProps } as LyricVideoProps;

  // Fallback for duration (must be a number)
  const durationInFrames = (passedProps.durationInFrames as number) || 1800;
  const design = (props.design ?? {}) as { aspectRatio?: string; fps?: number };
  const fps = Number(design.fps || 30);
  const dimensions =
    design.aspectRatio === '9:16'
      ? { width: 1080, height: 1920 }
      : design.aspectRatio === '1:1'
        ? { width: 1080, height: 1080 }
        : { width: 1920, height: 1080 };

  return (
    <>
      <Composition
        id="LyricVideo"
        component={LyricVideo as React.FC<any>}
        durationInFrames={durationInFrames}
        fps={fps}
        width={dimensions.width}
        height={dimensions.height}
        defaultProps={props}
      />
    </>
  );
};

export default RemotionRoot;

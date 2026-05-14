import React from 'react';

// --- REMOTION MOCKS FOR PREVIEW ---
// The preview environment cannot resolve the 'remotion' package or local files.
// When running locally, replace this block with:
// import { Composition, getInputProps } from 'remotion';
// import { LyricVideo, LyricVideoProps } from './LyricVideo';

export interface LyricVideoProps {
  title: string;
  artist: string;
  audioUrl: string;
  timestampsUrl: string;
  durationInFrames?: number;
}

// Mocking getInputProps for the Canvas environment
const getInputProps = (): any => ({});

// Updated Composition mock: Changed Record<string, unknown> to object 
// to satisfy TypeScript's index signature requirements for interfaces.
const Composition = <T extends object>({ 
  id, 
  width, 
  height, 
  fps, 
  durationInFrames 
}: { 
  id: string, 
  component: React.ComponentType<T>, 
  width: number, 
  height: number, 
  fps: number, 
  durationInFrames: number, 
  defaultProps: T 
}) => (
  <div style={{
    width: '100%',
    height: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#0f0f0f',
    color: 'white',
    fontFamily: 'system-ui, sans-serif'
  }}>
    <div style={{
      height: '80%',
      aspectRatio: `${width}/${height}`,
      border: '2px solid #333',
      borderRadius: '12px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      textAlign: 'center',
      padding: '2rem',
      boxShadow: '0 20px 50px rgba(0,0,0,0.5)'
    }}>
      <div style={{ color: '#FFD700', fontSize: '1.5rem', fontWeight: 'bold', marginBottom: '1rem' }}>
        Composition: {id}
      </div>
      <div style={{ fontSize: '0.9rem', color: '#888', lineHeight: '1.6' }}>
        <p>Format: Vertical ({width}x{height})</p>
        <p>Framerate: {fps} FPS</p>
        <p>Duration: {durationInFrames} frames (~{Math.round(durationInFrames/fps)}s)</p>
      </div>
      <div style={{ marginTop: '2rem', padding: '1rem', background: '#1a1a1a', borderRadius: '8px', border: '1px solid #333' }}>
        <p style={{ margin: 0, fontSize: '0.8rem' }}>LyricVideo.tsx logic loaded</p>
      </div>
    </div>
  </div>
);

const LyricVideo: React.FC<LyricVideoProps> = () => null;
// --- END REMOTION MOCKS ---

export const RemotionRoot: React.FC = () => {
  // getInputProps reads the dynamic props passed from the Python worker
  const passedProps = getInputProps();

  // Explicitly typing the default props ensures they match the LyricVideoProps interface
  const defaultProps: LyricVideoProps = {
    title: 'Test Track',
    artist: 'EchoForge Band',
    audioUrl: 'audio.mp3',
    timestampsUrl: 'timestamps.json',
  };

  // Merge passed props with defaults and cast to the correct interface
  const props = { ...defaultProps, ...passedProps } as LyricVideoProps;

  // Fallback for duration (must be a number)
  const durationInFrames = (passedProps.durationInFrames as number) || 1800;

  return (
    <>
      <Composition<LyricVideoProps>
        id="LyricVideo"
        component={LyricVideo}
        durationInFrames={durationInFrames}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={props}
      />
    </>
  );
};

export default RemotionRoot;
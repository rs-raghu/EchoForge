import { Config } from '@remotion/cli/config';

// -----------------------------------------------------------
// EchoForge: Remotion Rendering Engine Configuration
// -----------------------------------------------------------

// Set the image format used for rendering frames (jpeg is faster, png supports transparency)
Config.setVideoImageFormat('jpeg');

// Automatically overwrite the final_video.mp4 if it already exists 
// (prevents the background worker from crashing on retries)
Config.setOverwriteOutput(true);

// Set the maximum time allowed for a single frame to render
// (We increase this slightly just in case high-res custom backgrounds take a moment to load)
Config.setDelayRenderTimeoutInMilliseconds(120000);

// (Optional) You can customize how Remotion handles external assets or fonts here.
// For standard EchoForge usage with local workspace files, the defaults are perfect!
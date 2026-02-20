import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Html5Audio, Img, staticFile, Sequence, spring } from 'remotion';
import React from 'react';

// ============================================================================
// PART 1: THE DATA 
// This represents the JSON file that our Python backend (Whisper) will eventually give us.
// ============================================================================
const SONG_DATA = {
	title: "Echoes in the Code",
	artist: "Raghu ft. AI",
	lyrics: [
		// 'start' and 'end' are in seconds.
		{ text: "Hello Raghu, welcome to", start: 1.5, end: 3.5 },
		{ text: "the EchoForge Engine.", start: 3.5, end: 5.5 },
	]
};

// ============================================================================
// PART 2: THE MAIN ENGINE
// This component manages the timeline and decides WHEN things happen.
// ============================================================================
export const Playground: React.FC = () => {
	
	// --- HOOKS ---
	// Hooks must ALWAYS be at the very top of a component.
	// useVideoConfig() gives us global settings from Root.tsx (like fps = 30)
	const { fps } = useVideoConfig();

	// --- THE MATH: DYNAMIC OFFSET ---
	// Problem: We want our Intro to be exactly 5 seconds long.
	// But what if the singer starts singing at 1.5 seconds? The lyrics will overlap the intro!
	
	const INTRO_DURATION_SEC = 5.0; 
	// Math.round() ensures we get a clean whole number (e.g., 5.0 * 30 = 150 frames)
	const INTRO_FRAMES = Math.round(INTRO_DURATION_SEC * fps); 
	
	// Find out exactly when the very first lyric starts
	const firstLyricStartSec = SONG_DATA.lyrics[0].start;
	const firstLyricStartFrames = Math.round(firstLyricStartSec * fps);

	// The Logic: 
	// Is the first lyric starting before our 150-frame intro finishes?
	// If YES -> Calculate the difference and delay the music by that amount.
	// If NO -> Give it a 0 frame delay (start immediately).
	const delayFrames = firstLyricStartFrames < INTRO_FRAMES 
		? INTRO_FRAMES - firstLyricStartFrames // Pushes it back just enough to clear the intro
		: 0; 
	// ------------------------------------

	// AbsoluteFill acts like a fullscreen div (width: 100%, height: 100%)
	return (
		<AbsoluteFill style={{ backgroundColor: '#000' }}>
			
			{/* LAYER 1: BACKGROUND */}
			{/* This sits at the bottom of our code, so it renders furthest back */}
			<Img 
				src="https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=1920&auto=format&fit=crop" 
				style={{ width: '100%', height: '100%', objectFit: 'cover', opacity: 0.3 }}
			/>

			{/* LAYER 2: THE AUDIO */}
			{/* We wrap it in a Sequence so we can shift it forward in time using 'delayFrames' */}
			<Sequence from={delayFrames}>
				<Html5Audio src={staticFile("bgm.mp3")} />
			</Sequence>

			{/* LAYER 3: SCENE 1 - Intro Logo (0s to 2.5s) */}
			{/* It starts at frame 0, and lasts for 75 frames (2.5 * 30) */}
			<Sequence from={0} durationInFrames={fps * 2.5}>
				<IntroLogo />
			</Sequence>

			{/* LAYER 4: SCENE 2 - Cinematic Title Reveal (2.5s to 5s) */}
			{/* It starts exactly when Scene 1 ends (fps * 2.5) */}
			<Sequence from={fps * 2.5} durationInFrames={fps * 2.5}>
				{/* We pass 'title' and 'artist' down as "Props" so the component knows what to display */}
				<SongTitle title={SONG_DATA.title} artist={SONG_DATA.artist} />
			</Sequence>

			{/* LAYER 5: SCENE 3 - The Lyrics */}
			{/* This entire block of lyrics is pushed back by the 'delayFrames' variable */}
			<Sequence from={delayFrames}>
				{/* .map() loops through our JSON array and creates a Sequence for each line */}
				{SONG_DATA.lyrics.map((line, index) => {
					const startFrame = Math.round(line.start * fps);
					const endFrame = Math.round(line.end * fps);
					const duration = endFrame - startFrame;

					return (
						// Each line gets its own strict start and stop time on the timeline
						<Sequence key={index} from={startFrame} durationInFrames={duration}>
							<AnimatedLine text={line.text} duration={duration} />
						</Sequence>
					);
				})}
			</Sequence>

		</AbsoluteFill>
	);
};


// ============================================================================
// PART 3: THE ACTORS (Sub-Components)
// Rule of React: We keep these OUTSIDE the main Playground component 
// so they don't cause "Invalid Hook" errors or re-render unnecessarily.
// ============================================================================


// --- ACTOR 1: INTRO LOGO ---
const IntroLogo: React.FC = () => {
	// Inside a Sequence, useCurrentFrame() resets to 0. 
	// So frame 0 here is actually the start of THIS specific scene.
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	
	// interpolate() maps the timeline to CSS.
	// Input: Frame [0 to 15], then [60 to 75]
	// Output: Opacity [0 to 1] (Fade In), then [1 to 0] (Fade Out)
	const opacity = interpolate(frame, [0, 15, fps * 2.5 - 15, fps * 2.5], [0, 1, 1, 0]);
	
	// spring() is a physics engine. It makes the scaling bouncy instead of robotic.
	const scale = spring({ fps, frame, config: { damping: 12 } });

	return (
		<AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', opacity }}>
			<div style={{ fontSize: 150, transform: `scale(${scale})` }}>🚀</div>
			<h1 style={{ color: 'white', fontFamily: 'sans-serif', fontSize: 60, marginTop: 20 }}>EchoForge Studio</h1>
		</AbsoluteFill>
	);
};


// --- ACTOR 2: SONG TITLE ---
// The { title, artist } inside the parenthesis tells React to expect those inputs (Props).
const SongTitle: React.FC<{ title: string, artist: string }> = ({ title, artist }) => {
	const frame = useCurrentFrame();
	const { fps } = useVideoConfig();
	
	// filter: blur() interpolation. Starts at 20px blur, goes to 0px (sharp) over 30 frames.
	const blur = interpolate(frame, [0, 30], [20, 0], { extrapolateRight: 'clamp' });
	
	// Slow, continuous zoom in. Scales from 90% (0.9) to 110% (1.1) over the whole 2.5 seconds.
	const scale = interpolate(frame, [0, fps * 2.5], [0.9, 1.1]);
	
	const opacity = interpolate(frame, [0, 15, fps * 2.5 - 15, fps * 2.5], [0, 1, 1, 0]);

	return (
		<AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', opacity }}>
			<div style={{ 
				transform: `scale(${scale})`, 
				filter: `blur(${blur}px)`,
				textAlign: 'center' 
			}}>
				<h1 style={{ color: 'white', fontFamily: 'serif', fontSize: 100, margin: 0, fontStyle: 'italic' }}>"{title}"</h1>
				<h2 style={{ color: '#aaa', fontFamily: 'sans-serif', fontSize: 50, margin: 20, letterSpacing: '10px' }}>{artist.toUpperCase()}</h2>
			</div>
		</AbsoluteFill>
	);
};


// --- ACTOR 3: LYRICS LINE ---
const AnimatedLine: React.FC<{ text: string, duration: number }> = ({ text, duration }) => {
	const frame = useCurrentFrame();
	
	// Fades in over the first 15 frames of the word, stays solid, then fades out over the last 15 frames.
	const opacity = interpolate(frame, [0, 15, duration - 15, duration], [0, 1, 1, 0]);

	return (
		<AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center' }}>
			<h1 style={{
				fontSize: 100, fontWeight: 'bold', color: 'white', fontFamily: 'sans-serif',
				textShadow: '0px 10px 20px rgba(0,0,0,0.8)', opacity, width: '80%', textAlign: 'center'
			}}>
				{text}
			</h1>
		</AbsoluteFill>
	);
};
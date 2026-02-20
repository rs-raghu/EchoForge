import { Composition } from 'remotion';
import { Playground } from './Playground'; // <-- Import your new file

export const RemotionRoot: React.FC = () => {
	return (
		<>
			<Composition
				id="Sandbox"
				component={Playground}
				durationInFrames={30 * 6} // 6 seconds long
				fps={30}
				width={1920}
				height={1080} // 9:16 Vertical format
			/>
		</>
	);
};
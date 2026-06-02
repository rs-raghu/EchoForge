import { registerRoot } from 'remotion';
import { RemotionRoot } from './Root';

// This is the absolute core of Remotion. 
// It tells the engine "Hey, look inside RemotionRoot for all the video compositions!"
registerRoot(RemotionRoot);
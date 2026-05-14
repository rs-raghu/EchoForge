import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";

// This registers your main composition so the Remotion CLI can find it
// when the Orchestrator runs: `npx remotion render src/index.ts ...`
registerRoot(RemotionRoot);
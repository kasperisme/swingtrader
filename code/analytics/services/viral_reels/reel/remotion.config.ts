import {Config} from '@remotion/cli/config';

// Vertical reel defaults. Per-spec width/height/fps are driven by
// calculateMetadata in Root.tsx; these are render-pipeline settings.
Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
Config.setCodec('h264');
Config.setConcurrency(null);

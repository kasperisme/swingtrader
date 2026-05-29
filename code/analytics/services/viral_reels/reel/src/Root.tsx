import React from 'react';
import {Composition} from 'remotion';
import {BarChartRace} from './compositions/BarChartRace';
import {ReelSpec} from './types';
import sampleSpec from '../samples/sample_spec.json';

const spec = sampleSpec as unknown as ReelSpec;
const fps = spec.format.fps;

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="BarChartRace"
      component={BarChartRace}
      defaultProps={{spec}}
      fps={fps}
      width={spec.format.width}
      height={spec.format.height}
      durationInFrames={Math.round(spec.format.durationInSeconds * fps)}
      calculateMetadata={({props}) => {
        const f = props.spec.format;
        return {
          durationInFrames: Math.round(f.durationInSeconds * f.fps),
          fps: f.fps,
          width: f.width,
          height: f.height,
        };
      }}
    />
  );
};

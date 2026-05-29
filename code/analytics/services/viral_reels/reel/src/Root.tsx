import React from 'react';
import {Composition} from 'remotion';
import {BarChartRace} from './compositions/BarChartRace';
import {PriceNewsChart} from './compositions/PriceNewsChart';
import {ReelSpec, PriceNewsSpec} from './types';
import sampleSpec from '../samples/sample_spec.json';
import priceNewsSample from '../samples/price_news_sample_spec.json';

const spec = sampleSpec as unknown as ReelSpec;
const priceSpec = priceNewsSample as unknown as PriceNewsSpec;

const metaFromFormat = (f: {durationInSeconds: number; fps: number; width: number; height: number}) => ({
  durationInFrames: Math.round(f.durationInSeconds * f.fps),
  fps: f.fps,
  width: f.width,
  height: f.height,
});

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="BarChartRace"
        component={BarChartRace}
        defaultProps={{spec}}
        fps={spec.format.fps}
        width={spec.format.width}
        height={spec.format.height}
        durationInFrames={Math.round(spec.format.durationInSeconds * spec.format.fps)}
        calculateMetadata={({props}) => metaFromFormat(props.spec.format)}
      />
      <Composition
        id="PriceNewsChart"
        component={PriceNewsChart}
        defaultProps={{spec: priceSpec}}
        fps={priceSpec.format.fps}
        width={priceSpec.format.width}
        height={priceSpec.format.height}
        durationInFrames={Math.round(priceSpec.format.durationInSeconds * priceSpec.format.fps)}
        calculateMetadata={({props}) => metaFromFormat(props.spec.format)}
      />
    </>
  );
};

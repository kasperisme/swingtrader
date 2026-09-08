import React from 'react';
import {Composition} from 'remotion';
import {BarChartRace} from './compositions/BarChartRace';
import {PriceNewsChart} from './compositions/PriceNewsChart';
import {StockCard} from './compositions/StockCard';
import {ArenaTable} from './compositions/ArenaTable';
import {ArenaRace} from './compositions/ArenaRace';
import {ReelSpec, PriceNewsSpec, CardReelSpec, ArenaTableSpec, ArenaRaceSpec} from './types';
import sampleSpec from '../samples/sample_spec.json';
import priceNewsSample from '../samples/price_news_sample_spec.json';
import cardSample from '../samples/card_sample_spec.json';
import arenaTableSample from '../samples/arena_table_sample_spec.json';
import arenaRaceSample from '../samples/arena_race_sample_spec.json';

const spec = sampleSpec as unknown as ReelSpec;
const priceSpec = priceNewsSample as unknown as PriceNewsSpec;
const cardSpec = cardSample as unknown as CardReelSpec;
const arenaTableSpec = arenaTableSample as unknown as ArenaTableSpec;
const arenaRaceSpec = arenaRaceSample as unknown as ArenaRaceSpec;

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
      <Composition
        id="StockCard"
        component={StockCard}
        defaultProps={{spec: cardSpec}}
        fps={cardSpec.format.fps}
        width={cardSpec.format.width}
        height={cardSpec.format.height}
        durationInFrames={Math.round(cardSpec.format.durationInSeconds * cardSpec.format.fps)}
        calculateMetadata={({props}) => metaFromFormat(props.spec.format)}
      />
      {/* The Arena — the weekly league table (still) and the season race. */}
      <Composition
        id="ArenaTable"
        component={ArenaTable}
        defaultProps={{spec: arenaTableSpec}}
        fps={arenaTableSpec.format.fps}
        width={arenaTableSpec.format.width}
        height={arenaTableSpec.format.height}
        durationInFrames={1}
        calculateMetadata={({props}) => ({...metaFromFormat(props.spec.format), durationInFrames: 1})}
      />
      <Composition
        id="ArenaRace"
        component={ArenaRace}
        defaultProps={{spec: arenaRaceSpec}}
        fps={arenaRaceSpec.format.fps}
        width={arenaRaceSpec.format.width}
        height={arenaRaceSpec.format.height}
        durationInFrames={Math.round(arenaRaceSpec.format.durationInSeconds * arenaRaceSpec.format.fps)}
        calculateMetadata={({props}) => metaFromFormat(props.spec.format)}
      />
    </>
  );
};

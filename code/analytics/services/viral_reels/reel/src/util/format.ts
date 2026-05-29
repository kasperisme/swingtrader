import {ValueFormat} from '../types';

export const formatValue = (value: number, fmt: ValueFormat): string => {
  switch (fmt) {
    case 'count':
      return Math.round(value).toLocaleString('en-US');
    case 'percent':
      return `${(value * 100).toFixed(0)}%`;
    case 'currency':
      return value >= 1000
        ? `$${(value / 1000).toFixed(1)}k`
        : `$${value.toFixed(2)}`;
    case 'signed':
      return `${value >= 0 ? '+' : ''}${value.toFixed(2)}`;
    case 'score':
    default:
      return value.toFixed(2);
  }
};

export const formatPrice = (value: number): string =>
  value >= 1000 ? value.toLocaleString('en-US', {maximumFractionDigits: 0}) : value.toFixed(2);

import {expect,it} from 'vitest';
import {collectionPage} from './pagination';

it('replaces pagination while preserving collection filters',()=>{
  const path=collectionPage('/runs?status=failed&offset=9&limit=200',50,50);
  const query=new URLSearchParams(path.split('?')[1]);
  expect(path.split('?')[0]).toBe('/runs');
  expect(query.get('status')).toBe('failed');
  expect(query.getAll('offset')).toEqual(['50']);
  expect(query.getAll('limit')).toEqual(['50']);
});

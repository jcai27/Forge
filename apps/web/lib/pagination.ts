'use client';
import {useInfiniteQuery} from '@tanstack/react-query';
import type {Collection} from '../../../packages/contracts/src';
import {api} from './api';

export function collectionPage(path:string,offset:number,limit:number) {
  const [pathname,search='']=path.split('?');
  const query=new URLSearchParams(search);
  query.set('offset',String(offset));query.set('limit',String(limit));
  return `${pathname}?${query}`;
}

export function usePagedCollection<T extends {id:string}>(path:string,enabled=true,poll=0) {
  const query=useInfiniteQuery({
    queryKey:['collection',path],enabled:enabled&&Boolean(path),initialPageParam:0,
    queryFn:({pageParam})=>api<Collection<T>>(collectionPage(path,pageParam,50)),
    getNextPageParam:last=>last.items.length&&last.offset+last.limit<last.total?last.offset+last.limit:undefined,
    // Loaded pages refresh together; scale polling to keep large lists within API limits.
    refetchInterval:poll?(state)=>poll*Math.max(1,state.state.data?.pages.length??1):false,
  });
  const pages=query.data?.pages;
  const seen=new Set<string>();
  const items=pages?.flatMap(page=>page.items).filter(item=>{if(seen.has(item.id))return false;seen.add(item.id);return true;});
  return {...query,data:pages&&items?{...pages[0],items}:undefined};
}

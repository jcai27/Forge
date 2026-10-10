'use client';
import {Button} from './ui/button';

type PagedResource={data?:{items:unknown[];total:number};hasNextPage:boolean;isFetchingNextPage:boolean;fetchNextPage:()=>Promise<unknown>};
export function CollectionMore({resource,label}:{resource:PagedResource;label:string}) {
  if(!resource.data||!resource.hasNextPage)return null;
  return <div className="row wrap" style={{margin:'16px 0'}}><Button type="button" variant="secondary" disabled={resource.isFetchingNextPage} onClick={()=>void resource.fetchNextPage()}>{resource.isFetchingNextPage?'Loading…':`Load more ${label}`}</Button><span className="help">Showing {resource.data.items.length} of {resource.data.total} {label}</span></div>;
}

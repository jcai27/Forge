'use client';
import {useEffect, useState} from 'react';
import {API_URL, token} from '@/lib/api';

/** A stored page image. It needs the sign-in token, so it is fetched and shown from memory, not by address. */
export function StoredPage({path, label}: {path: string; label: string}) {
  const [source, setSource] = useState(''), [failed, setFailed] = useState(false);
  useEffect(() => {
    let address = '', stopped = false;
    fetch(API_URL + path, {headers: {Authorization: `Bearer ${token()}`}})
      .then(response => response.ok ? response.blob() : Promise.reject(new Error('unavailable')))
      .then(blob => {if (stopped) return; address = URL.createObjectURL(blob); setSource(address);})
      .catch(() => {if (!stopped) setFailed(true);});
    return () => {stopped = true; if (address) URL.revokeObjectURL(address);};
  }, [path]);
  if (failed) return <p className="muted small">This page image is no longer stored.</p>;
  if (!source) return <div className="muted small" style={{padding:24}}>Loading page…</div>;
  // eslint-disable-next-line @next/next/no-img-element -- an in-memory image of a private document
  return <a href={source} target="_blank" rel="noreferrer" title="Open at full size"><img src={source} alt={label} style={{width:'100%',display:'block',border:'1px solid var(--line)',borderRadius:6,background:'#fff'}}/></a>;
}

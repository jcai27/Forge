'use client';
import {useEffect, useState} from 'react';
import {API_URL, token} from '@/lib/api';

/** A stored page image. It needs the sign-in token, so it is fetched and shown from memory, not by address. */
export function StoredPage({path, label}: {path: string; label: string}) {
  const [source, setSource] = useState(''), [failed, setFailed] = useState(false), [large, setLarge] = useState(false);
  useEffect(() => {
    let address = '', stopped = false;
    fetch(API_URL + path, {headers: {Authorization: `Bearer ${token()}`}})
      .then(response => response.ok ? response.blob() : Promise.reject(new Error('unavailable')))
      .then(blob => {if (stopped) return; address = URL.createObjectURL(blob); setSource(address);})
      .catch(() => {if (!stopped) setFailed(true);});
    return () => {stopped = true; if (address) URL.revokeObjectURL(address);};
  }, [path]);
  useEffect(() => {
    if (!large) return;
    const close = (event: KeyboardEvent) => {if (event.key === 'Escape') setLarge(false);};
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [large]);
  if (failed) return <p className="muted small">This page image is no longer stored.</p>;
  if (!source) return <div className="muted small" style={{padding:24}}>Loading page…</div>;
  /* eslint-disable @next/next/no-img-element -- an in-memory image of a private document */
  return <>
    <button type="button" className="page-thumb" onClick={() => setLarge(true)} title="Enlarge" aria-label={`Enlarge ${label}`}><img src={source} alt={label}/></button>
    {large && <div className="page-zoom" role="dialog" aria-modal="true" aria-label={label} onClick={() => setLarge(false)}><button type="button" className="page-zoom-close" aria-label="Close">Close (Esc)</button><img src={source} alt={label} onClick={event => event.stopPropagation()}/></div>}
  </>;
}

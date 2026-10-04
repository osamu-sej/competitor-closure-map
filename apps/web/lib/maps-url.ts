import type { Store } from './types';

// Opens an independent Google Maps search for human verification. No Google
// Places content is imported into the app's OpenPOI store master.
export function googleMapsSearchUrl(store:Store):string {
  const location=store.address||`${store.prefecture} ${store.city}`.trim();
  const query=[store.canonical_name,location].filter(Boolean).join(', ').slice(0,1000);
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

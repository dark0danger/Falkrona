import { useId } from "react";

export function CampaignArt() {
  const id = useId();
  const fill = (name: string) => `url(#${id}-${name})`;
  return <svg className="campaign-art" viewBox="0 0 430 340" fill="none" aria-hidden="true">
    <defs>
      <linearGradient id={`${id}-paper`} x1="0" x2="1" y2="1" gradientUnits="objectBoundingBox"><stop stopColor="#fbf4ff"/><stop offset="1" stopColor="#c9bce9"/></linearGradient>
      <linearGradient id={`${id}-leaf`} x1="0" x2="1" y1="1" y2="0"><stop stopColor="#211b47"/><stop offset=".45" stopColor="#3d316f"/><stop offset="1" stopColor="#a598cd"/></linearGradient>
      <linearGradient id={`${id}-cup`}><stop stopColor="#a39ac7"/><stop offset=".42" stopColor="#625787"/><stop offset="1" stopColor="#30274e"/></linearGradient>
      <radialGradient id={`${id}-coffee`}><stop stopColor="#a49abf"/><stop offset=".68" stopColor="#544766"/><stop offset="1" stopColor="#28223f"/></radialGradient>
      <filter id={`${id}-shadow`} x="-50%" y="-40%" width="220%" height="230%"><feDropShadow dx="1" dy="12" stdDeviation="11" floodColor="#100e33" floodOpacity=".52"/></filter>
      <clipPath id={`${id}-scenery`}><rect width="144" height="221" rx="16"/></clipPath>
      <clipPath id={`${id}-drink`}><rect width="146" height="220" rx="16"/></clipPath>
      <g id={`${id}-sprig`}>
        <path d="M0 0C-29-25-26-63 4-101 8-78 40-48 0 0Z" fill={fill("leaf")}/>
        <path d="M0 0C1-34 6-64 4-101M1-20c-10-7-17-17-21-26M3-36c10-9 16-19 20-29M4-53c-8-7-13-14-15-23M5-70c5-5 8-10 10-14" stroke="#c8b9e4" strokeOpacity=".52" strokeWidth="1.2"/>
      </g>
    </defs>
    <g transform="translate(24 91) rotate(-11 73 110)" filter={fill("shadow")}>
      <g clipPath={fill("drink")}>
        <rect width="146" height="220" rx="16" fill={fill("paper")}/>
        <ellipse cx="78" cy="157" rx="60" ry="32" fill="#7e709d" opacity=".34"/>
        <path d="M112 104c41-19 45 32 6 35" stroke="#766a9a" strokeWidth="10"/>
        <path d="M21 102c0 48 20 68 55 68 35 0 55-21 55-68Z" fill={fill("cup")}/>
        <ellipse cx="76" cy="102" rx="56" ry="30" fill="#b3a8d5"/>
        <ellipse cx="76" cy="102" rx="50" ry="25" fill={fill("coffee")}/>
        <path d="M76 120c-24-9-29-20-23-24 7-5 15 8 22 10-18-12-13-20-8-18 5 1 8 9 10 12-4-12 0-17 4-14 3 3 1 10-3 16 8-12 17-15 17-10 0 6-9 12-16 17 11-8 22-12 22-5 0 7-13 12-25 16Z" fill="#eee4ff" opacity=".86"/>
        <path d="M77 99v22" stroke="#e9dbff" strokeWidth="1.8"/>
        <rect x="19" y="21" width="52" height="6" rx="3" fill="#8c7ec3"/>
      </g>
    </g>
    <g transform="translate(257 89) rotate(12 72 110)" filter={fill("shadow")}>
      <g clipPath={fill("scenery")}>
        <rect width="144" height="221" rx="16" fill={fill("paper")}/>
        <path d="M0 103 39 52l17 13 13-11 21 28 16 8 14 13 24 6v82H0Z" fill="#ad9fce"/>
        <path d="M0 123 30 96l21 20 20-21 13 18 32-30 28 25v83H0Z" fill="#8f7eba"/>
        <path d="m0 156 28-18 32-9 35 8 20-16 29-13v85H0Z" fill="#665792"/>
        <path d="M0 176 17 150l5 10 8-22 7 19 6-12 9 20 12-19 8 18 12-29 9 18 11-23 8 12 10-18 5 12 10-19 7 12v57H0Z" fill="#483d75"/>
        <rect y="181" width="144" height="44" fill="#d5c9ec"/>
      </g>
    </g>
    <g transform="translate(134 41) rotate(-1.3 99 142)" filter={fill("shadow")}>
      <rect width="198" height="286" rx="18" fill={fill("paper")} stroke="#f5edff" strokeWidth="1.5"/>
      <path d="M130 221c-9-39-5-67 4-98M128 202c-16-34-35-45-60-55M128 209c-31-11-53-12-69-11M129 213c19-15 27-35 27-50" stroke="#483a6b" strokeWidth="2.5" strokeLinecap="round"/>
      <use href={`#${id}-sprig`} transform="translate(131 155) rotate(22) scale(1.12)"/>
      <use href={`#${id}-sprig`} transform="translate(113 177) rotate(-51) scale(.92 .97)"/>
      <use href={`#${id}-sprig`} transform="translate(106 200) rotate(-86) scale(.76 .83)"/>
      <use href={`#${id}-sprig`} transform="translate(135 210) rotate(31) scale(.65 .72)"/>
      <rect x="1" y="221" width="196" height="63" rx="16" fill="#eee4fb" opacity=".88"/>
      <path d="M25 25h48m-48 16h26M26 245h96m-96 16h60" stroke="#8979c1" strokeWidth="7" strokeLinecap="round"/>
    </g>
  </svg>;
}

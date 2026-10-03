export function cairoInput(instant: string): string {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {timeZone:"Africa/Cairo", year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23"})
    .formatToParts(new Date(instant)).map(part=>[part.type,part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

export function lastDayOfWeek(week: string): string {
  const date = new Date(`${week}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate()+6);
  return date.toISOString().slice(0,10);
}

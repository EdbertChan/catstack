export function classifyFailure(errorText: string): string {
  if (errorText.includes('No space left on device')) {
    return 'disk_full';
  }
  return 'unknown';
}

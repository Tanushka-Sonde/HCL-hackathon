export type Role = 'admin' | 'editor' | 'viewer';

export function canUploadDocument(role: string): boolean {
  return role === 'admin' || role === 'editor';
}

export function canDeleteDocument(role: string): boolean {
  return role === 'admin' || role === 'editor';
}

export function canManageTeam(role: string): boolean {
  return role === 'admin';
}

export function canInviteMembers(role: string): boolean {
  return role === 'admin';
}

export function canSearch(role: string): boolean {
  // Everyone can search
  return true;
}

export function canEvaluate(role: string): boolean {
  // Everyone can evaluate
  return true;
}

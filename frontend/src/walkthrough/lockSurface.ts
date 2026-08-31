/**
 * Camera-surface DOM ownership id (originally the PR #10 pointer-lock
 * selector). Pointer lock was removed in the Phase 15 browser-acceptance
 * hotfix — the walkthrough is keyboard-only — but the persistent id keeps
 * documenting the MineViewportShell ownership split: canvas + HUD live on
 * the camera surface, while ordinary interactive UI (the inspector) stays
 * a sibling OUTSIDE it (Phase 14 §15/PR #11 blocker 2 contract).
 */
export const WALKTHROUGH_LOCK_SURFACE_ID = 'walkthrough-lock-surface'

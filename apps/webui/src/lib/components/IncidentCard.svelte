<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Tone } from './types';

	interface Props {
		tone?: Tone;
		title: string;
		description?: string;
		timestamp?: string | Date;
		source?: string;
		/**
		 * Failed-tone incidents must surface action buttons (Retry / Logs / Detail).
		 * Provide them via the `actions` snippet.
		 */
		actions?: Snippet;
		children?: Snippet;
	}

	let {
		tone = 'warning',
		title,
		description,
		timestamp,
		source,
		actions,
		children
	}: Props = $props();

	const TONE_GLYPH: Record<Tone, string> = {
		success: '✓',
		warning: '!',
		danger:  '✕',
		active:  '●',
		info:    'i',
		neutral: '·'
	};

	function formatTs(ts: string | Date | undefined): string {
		if (!ts) return '';
		try {
			const d = ts instanceof Date ? ts : new Date(ts);
			return d.toLocaleString();
		} catch {
			return String(ts);
		}
	}
</script>

<article class="inc" data-tone={tone} role="status">
	<div class="inc-marker" aria-hidden="true">
		<span class="inc-glyph">{TONE_GLYPH[tone]}</span>
	</div>
	<div class="inc-body">
		<h4 class="inc-title">{title}</h4>
		{#if source}<p class="inc-source mono">{source}</p>{/if}
		{#if description}<p class="inc-desc">{description}</p>{/if}
		{#if children}<div class="inc-extra">{@render children()}</div>{/if}
		{#if timestamp || actions}
			<div class="inc-meta-row">
				{#if timestamp}
					<time class="inc-timestamp" datetime={timestamp instanceof Date ? timestamp.toISOString() : String(timestamp)}>
						{formatTs(timestamp)}
					</time>
				{:else}
					<span></span>
				{/if}
				{#if actions}
					<div class="inc-actions" role="group" aria-label="Incident actions">
						{@render actions()}
					</div>
				{/if}
			</div>
		{/if}
	</div>
</article>

<style>
	.inc {
		display: flex;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		background: var(--panel);
		border: 1px solid var(--panel-border);
		border-left: 3px solid currentColor;
		border-radius: var(--radius-md);
	}
	.inc[data-tone='success'] { color: var(--success); }
	.inc[data-tone='warning'] { color: var(--warning); }
	.inc[data-tone='danger']  { color: var(--danger); }
	.inc[data-tone='active']  { color: var(--brand); }
	.inc[data-tone='info']    { color: var(--cyan); }
	.inc[data-tone='neutral'] { color: var(--muted-strong); }

	.inc-marker {
		flex: 0 0 auto;
		width: 1.5rem;
		height: 1.5rem;
		border-radius: var(--radius-circle);
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background: currentColor;
		color: #fff;
		margin-top: 2px;
	}
	.inc-glyph { font-size: var(--font-size-xs); font-weight: var(--font-weight-bold); }

	.inc-body { flex: 1 1 auto; min-width: 0; color: var(--text); }
	.inc-title {
		margin: 0;
		font-size: var(--font-size-sm);
		font-weight: var(--font-weight-semibold);
		color: var(--text);
	}
	.inc-timestamp {
		flex-shrink: 0;
		font-size: var(--font-size-2xs);
		color: var(--muted);
	}
	.inc-desc {
		margin: var(--space-1) 0 0;
		font-size: var(--font-size-xs);
		color: var(--muted-strong);
		line-height: var(--line-height-snug);
		display: -webkit-box;
		-webkit-line-clamp: 1;
		line-clamp: 1;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.inc-source {
		margin: var(--space-1) 0 0;
		font-size: var(--font-size-2xs);
		color: var(--muted);
	}
	.inc-extra { margin-top: var(--space-1); }
	.inc-meta-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-2);
	}
	.inc-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1);
	}
	.inc-actions :global(.button) {
		padding: 0.25rem 0.55rem;
		font-size: var(--font-size-2xs);
	}
</style>

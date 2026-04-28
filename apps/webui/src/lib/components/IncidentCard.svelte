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
		/** When true, the card renders a compact collapsed form with a chevron toggle. */
		collapsible?: boolean;
		/** Controlled expanded state (used when collapsible=true). Defaults to false. */
		expanded?: boolean;
		/** Fired when the user clicks the card body (only in collapsible mode). */
		onToggle?: () => void;
		/** Extra detail rendered only when expanded (traceback, links, related items). */
		expandedContent?: Snippet;
	}

	let {
		tone = 'warning',
		title,
		description,
		timestamp,
		source,
		actions,
		children,
		collapsible = false,
		expanded = false,
		onToggle,
		expandedContent
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

	function handleRootClick() {
		if (collapsible) onToggle?.();
	}
	function handleRootKeydown(e: KeyboardEvent) {
		if (!collapsible) return;
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			onToggle?.();
		}
	}
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<article
	class="inc"
	data-tone={tone}
	data-collapsible={collapsible ? 'true' : 'false'}
	data-expanded={collapsible ? (expanded ? 'true' : 'false') : undefined}
	role={collapsible ? 'button' : 'status'}
	tabindex={collapsible ? 0 : undefined}
	aria-expanded={collapsible ? expanded : undefined}
	onclick={collapsible ? handleRootClick : undefined}
	onkeydown={collapsible ? handleRootKeydown : undefined}
>
	<div class="inc-marker" aria-hidden="true">
		<span class="inc-glyph">{TONE_GLYPH[tone]}</span>
	</div>
	<div class="inc-body">
		<div class="inc-head">
			<h4 class="inc-title">{title}</h4>
			{#if collapsible}
				<span class="inc-chevron" aria-hidden="true">{expanded ? '▾' : '▸'}</span>
			{/if}
		</div>
		{#if source}<p class="inc-source mono">{source}</p>{/if}
		{#if description}<p class="inc-desc">{description}</p>{/if}
		{#if !collapsible || expanded}
			{#if children}<div class="inc-extra">{@render children()}</div>{/if}
			{#if expandedContent}<div class="inc-expanded">{@render expandedContent()}</div>{/if}
		{/if}
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
		transition: background 120ms ease;
	}
	.inc[data-tone='success'] { color: var(--success); }
	.inc[data-tone='warning'] { color: var(--warning); }
	.inc[data-tone='danger']  { color: var(--danger); }
	.inc[data-tone='active']  { color: var(--brand); }
	.inc[data-tone='info']    { color: var(--cyan); }
	.inc[data-tone='neutral'] { color: var(--muted-strong); }

	.inc[data-collapsible='true'] {
		cursor: pointer;
		min-height: 72px;
	}
	.inc[data-collapsible='true']:hover {
		background: var(--panel-hover, var(--panel));
	}
	.inc[data-collapsible='true'][data-expanded='false'] .inc-source,
	.inc[data-collapsible='true'][data-expanded='false'] .inc-desc {
		-webkit-line-clamp: 1;
		line-clamp: 1;
	}
	.inc[data-collapsible='true'][data-tone='warning'] {
		border-left-width: 2px;
		min-height: 60px;
	}

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
	.inc-head {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		justify-content: space-between;
	}
	.inc-title {
		margin: 0;
		font-size: var(--font-size-sm);
		font-weight: var(--font-weight-semibold);
		color: var(--text);
	}
	.inc-chevron {
		flex-shrink: 0;
		font-size: 0.7rem;
		color: var(--muted);
		transition: transform 120ms ease;
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
	.inc[data-expanded='true'] .inc-desc {
		-webkit-line-clamp: unset;
		line-clamp: unset;
		display: block;
		overflow: visible;
	}
	.inc-source {
		margin: var(--space-1) 0 0;
		font-size: var(--font-size-2xs);
		color: var(--muted);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.inc[data-expanded='true'] .inc-source {
		white-space: normal;
		overflow: visible;
	}
	.inc-extra { margin-top: var(--space-1); }
	.inc-expanded {
		margin-top: var(--space-2);
		padding-top: var(--space-2);
		border-top: 1px dashed var(--panel-border);
		font-size: var(--font-size-xs);
		color: var(--muted-strong);
	}
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
	.inc[data-collapsible='true'][data-expanded='false'] .inc-actions :global(.button) {
		padding: 0.2rem 0.45rem;
		font-size: 0.68rem;
		height: 28px;
	}
</style>

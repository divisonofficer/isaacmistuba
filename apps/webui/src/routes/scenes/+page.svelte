<script lang="ts">
	import { onMount } from 'svelte';
	import { listScenes, isaacCommand, registerIsaacScene } from '$lib/api';

	type Scene = Record<string, unknown>;

	let scenes: Scene[] = $state([]);
	let loading = $state(true);
	let search = $state('');
	let filter = $state<'all' | 'render-ready' | 'no-cameras'>('all');
	let showRegister = $state(false);
	let regForm = $state({ scene_id: '', usd_path: '', mitsuba_scene_ref: '', shape_map_ref: '' });

	onMount(async () => {
		try { scenes = (await listScenes()).scenes ?? []; } catch {}
		loading = false;
	});

	const filtered = $derived(scenes.filter((s) => {
		const matchSearch = !search || String(s.scene_id ?? '').toLowerCase().includes(search.toLowerCase());
		const matchFilter =
			filter === 'all' ? true :
			filter === 'render-ready' ? s.readiness_status === 'render-ready' :
			(Number(s.camera_count ?? 0) === 0);
		return matchSearch && matchFilter;
	}));

	async function sendCommand(sceneId: string, cmd: string) {
		try {
			const r = await isaacCommand(cmd, sceneId);
			alert(`Command queued: ${r.command_id ?? JSON.stringify(r)}`);
		} catch (e) {
			alert(`Error: ${e}`);
		}
	}

	async function register() {
		try {
			await registerIsaacScene(regForm);
			showRegister = false;
			scenes = (await listScenes()).scenes ?? [];
		} catch (e) {
			alert(`Error: ${e}`);
		}
	}
</script>

<div class="flex items-center gap-2 mt-4" style="flex-wrap:wrap">
	<input class="search-input" placeholder="Search scenes…" bind:value={search} />
	{#each ['all', 'render-ready', 'no-cameras'] as f}
		<button
			class="button button-subtle text-xs {filter === f ? 'nav-link-active' : ''}"
			onclick={() => filter = f as typeof filter}
		>{f}</button>
	{/each}
	<button class="button button-subtle text-xs" style="margin-left:auto" onclick={() => showRegister = !showRegister}>
		+ Register Scene
	</button>
</div>

{#if showRegister}
	<div class="panel mt-4">
		<div class="panel-label">Register Scene</div>
		<div class="grid lg:grid-cols-4 gap-3 mt-3">
			{#each Object.keys(regForm) as key}
				<div>
					<div class="text-xs muted" style="margin-bottom:0.3rem">{key}</div>
					<input class="search-input" style="width:100%" bind:value={regForm[key as keyof typeof regForm]} placeholder={key} />
				</div>
			{/each}
		</div>
		<div class="flex gap-2 mt-3">
			<button class="button button-primary text-xs" onclick={register}>Register</button>
			<button class="button button-subtle text-xs" onclick={() => showRegister = false}>Cancel</button>
		</div>
	</div>
{/if}

{#if loading}
	<div class="muted text-sm mt-4">Loading scenes…</div>
{:else if filtered.length === 0}
	<div class="empty-state-illustrated mt-6">
		<div class="empty-icon">🎬</div>
		<div class="empty-title">No scenes</div>
		<div class="empty-desc">No scenes match the current filter.</div>
	</div>
{:else}
	<div class="muted text-xs mt-3" style="margin-bottom:0.5rem">
		{filtered.length} scene{filtered.length !== 1 ? 's' : ''}
		{filter !== 'all' ? `· filtered by "${filter}"` : ''}
	</div>
	<div class="table-wrap">
		<table class="table">
			<thead>
				<tr>
					<th>Scene ID</th><th>Cameras</th><th>Ready</th><th>USD Path</th><th>Isaac Remote</th>
				</tr>
			</thead>
			<tbody>
				{#each filtered as scene}
					{@const s = scene}
					<tr>
						<td>
							<a href="/scenes/{s.scene_id}" class="link text-sm">{s.scene_id}</a>
						</td>
						<td class="text-sm">{s.camera_count ?? '—'}</td>
						<td>
							<span class="badge {s.readiness_status === 'render-ready' ? 'badge-succeeded' : 'badge-queued'}">
								{s.readiness_status ?? '—'}
							</span>
						</td>
						<td class="mono text-xs muted" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
							{s.usd_stage_path ?? s.usd_path ?? '—'}
						</td>
						<td>
							<div class="flex gap-2" style="flex-wrap:wrap">
								{#each [
									{ label: 'Load', cmd: 'load_scene' },
									{ label: 'Prepare', cmd: 'prepare_render_ready' },
									{ label: 'Connect', cmd: 'connect_session' },
									{ label: 'Sync', cmd: 'sync_state' },
									{ label: 'Render', cmd: 'render_current_view' }
								] as btn}
									<button class="button button-subtle text-xs" onclick={() => sendCommand(String(s.scene_id), btn.cmd)}>
										{btn.label}
									</button>
								{/each}
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

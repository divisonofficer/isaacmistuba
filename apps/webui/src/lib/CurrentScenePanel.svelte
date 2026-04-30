<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { lang } from '$lib/stores/lang';
	import { healthStore } from '$lib/stores/health';
	import { debugEvents } from '$lib/stores/debugEvents';
	import { sceneRailSnippet, sceneBottomSnippet } from '$lib/stores/scenePortals';
	import { bottomPanelCollapsed, toggleBottomPanel } from '$lib/stores/shell';
	import { currentSceneIdStore, currentSceneStore } from '$lib/stores/sceneCommands';
	import CurrentSceneBlueprint3D from '$lib/CurrentSceneBlueprint3D.svelte';
	import CurrentSceneNavigationMap from '$lib/CurrentSceneNavigationMap.svelte';
	import InlineMaterialPicker from '$lib/components/InlineMaterialPicker.svelte';
	import {
		summary, getIsaacSession, getIsaacSessionInventory,
		getScene, listJobs, materialPresets, materialLibrary,
		isaacCommand, smokeRender, applyMeasuredMaterial, applyCuratedMaterial,
		listIsaacScenes, listIsaacCommands, downloadDataset, getDatasetDownloadStatus,
		retryJob, deleteJob, prepareBasicScene, measuredMaterialPreviewUrl, curatedMaterialPreviewUrl
	} from '$lib/api';
	import { commandTypeLabel } from '$lib/stores/commandResultToasts';
	import { Card, IncidentCard, LogList, KeyValueList, DataTable, Breadcrumb, Tooltip } from '$lib/components';
	import type { LogEntry, KeyValueItem, DataTableColumn, Tone, BreadcrumbItem, TabItem } from '$lib/components';

	const L = $derived($lang);

	type ObjNode = {
		prim_path: string;
		name: string;
		kind?: string;
		children?: ObjNode[];
		visible?: boolean | null;
		has_override?: boolean;
		selected?: boolean;
		shape_count?: number;
	};
	type Preset = { bsdf_type: string; category: string; title_en: string; title_kr: string; description_en: string; description_kr: string; swatch?: string };
	type CategoryKey = 'metal' | 'plastic' | 'dielectric' | 'principled' | 'fluid' | 'fabric' | 'other';
	type MatEntry = {
		material_id: string;
		display_name: string;
		native_file: string;
		status: string;
		download_url: string | null;
		kind?: 'curated';
		category?: CategoryKey;
		description?: string;
		preview_baked?: boolean;
	};
	type DatasetGroup = {
		dataset_id: string; display_name: string; paper_title: string; venue: string;
		swatch_hue: number; patch_required: boolean; mitsuba_strategy: string;
		capabilities: { polarization: boolean; nir: boolean; spectral_range_nm: [number,number] };
		materials: MatEntry[];
	};

	type LayerKey = 'scene' | 'render' | 'shape';
	type ViewMode = '2d' | '3d' | 'nav';
	type BottomTabId = 'jobs' | 'logs' | 'selection' | 'history' | 'materials';
	type LiveCameraPayload = {
		scene_id?: string;
		updated_at?: string;
		sensor_revision?: number;
		active_viewport_camera?: Record<string, unknown> | null;
	};
	type JobRow = {
		job_id: string;
		status: string;
		stage: string;
		scene_id: string;
		finished_at: string;
	};

	const STAGES = [
		{ key: 'starting',         en: 'Start',     kr: '시작' },
		{ key: 'staging_scene',    en: 'Stage XML', kr: 'XML' },
		{ key: 'loading_scene',    en: 'Load GPU',  kr: 'GPU' },
		{ key: 'rendering',        en: 'Render',    kr: '렌더' },
		{ key: 'saving_output',    en: 'Save',      kr: '저장' },
		{ key: 'writing_manifest', en: 'Manifest',  kr: '매니' },
		{ key: 'complete',         en: 'Done',      kr: '완료' },
	];
	const STAGE_ORDER: Record<string, number> = Object.fromEntries(STAGES.map((s, i) => [s.key, i]));
	function stageIndex(stage: string | null | undefined): number {
		if (!stage) return -1;
		if (stage in STAGE_ORDER) return STAGE_ORDER[stage];
		if (['ambient', 'active', 'polar'].includes(stage)) return STAGE_ORDER['rendering'];
		return -1;
	}

	// Scene state
	let currentSceneId = $state<string | null>(null);
	let scene = $state<Record<string, unknown> | null>(null);
	let session = $state<Record<string, unknown> | null>(null);
	let objectInventory = $state<ObjNode[]>([]);
	let recentJobs = $state<Record<string, unknown>[]>([]);
	let recentIsaacCommands = $state<Record<string, unknown>[]>([]);
	let registeredScenes = $state<Record<string, unknown>[]>([]);

	// Material state
	let presets = $state<Preset[]>([]);
	let matGroups = $state<DatasetGroup[]>([]);
	let matSearch = $state('');
	let matCapFilter = $state<'all' | 'polarized' | 'nir' | 'available'>('all');
	let activeCategory = $state<'all' | CategoryKey>('all');
	const CATEGORY_CHIPS: { key: 'all' | CategoryKey; label_kr: string; label_en: string }[] = [
		{ key: 'all',         label_kr: '전체',         label_en: 'All' },
		{ key: 'metal',       label_kr: '금속',         label_en: 'Metal' },
		{ key: 'plastic',     label_kr: '플라스틱',     label_en: 'Plastic' },
		{ key: 'dielectric',  label_kr: '유전체',       label_en: 'Dielectric' },
		{ key: 'principled',  label_kr: '프린시폴드',   label_en: 'Principled' },
		{ key: 'fluid',       label_kr: '유체',         label_en: 'Fluid' },
		{ key: 'fabric',      label_kr: '패브릭',       label_en: 'Fabric' },
		{ key: 'other',       label_kr: '기타',         label_en: 'Other' }
	];
	let collapsedGroups = $state<Set<string>>(new Set());
	let dlJobs = $state<Record<string, { done: number; total: number; status: string; current_name?: string; error?: string }>>({});

	// Tree expand/collapse state — by prim_path
	let collapsedNodes = $state<Set<string>>(new Set());
	let treeInitializedSceneId = $state<string | null>(null);
	let treeFilter = $state('');

	// Map state
	let floorplan = $state<Record<string, unknown> | null>(null);
	let floorplanImgSrc = $state<string | null>(null);
	let floorplanError = $state('');
	let mapImg = $state<HTMLImageElement | null>(null);
	let mapCanvas = $state<HTMLCanvasElement | null>(null);
	let mapViewport = $state<HTMLDivElement | null>(null);
	let mapZoom = $state(1);
	let mapPanX = $state(0);
	let mapPanY = $state(0);
	let isPanning = $state(false);
	let liveActiveViewportCamera = $state<Record<string, unknown> | null>(null);
	let panStart = { x: 0, y: 0, px: 0, py: 0 };
	let currentSceneSocket: WebSocket | null = null;
	let currentSceneSocketSceneId: string | null = null;
	let currentSceneSocketRetry: ReturnType<typeof setTimeout> | null = null;
	let currentSceneSocketClosedByUs = false;

	// UI state
	let loading = $state(true);
	let selectedPaths = $state<Set<string>>(new Set());
	let primarySelectedPath = $state<string | null>(null);
	let selectionAnchorPath: string | null = null;
	let lastUserSelectionEditMs = 0;
	let lastExternalSelectionSignature = '';
	const cmpSelectionSignature = (paths: string[]) => paths.slice().sort().join('|');
	const cmpSelectionFromState = () => cmpSelectionSignature([...selectedPaths]);
	function findNodeByPath(nodes: ObjNode[], path: string): ObjNode | null {
		for (const n of nodes) {
			if (n.prim_path === path) return n;
			if (n.children) {
				const hit = findNodeByPath(n.children, path);
				if (hit) return hit;
			}
		}
		return null;
	}
	function visibleFlatTreePaths(): string[] {
		const out: string[] = [];
		const walk = (nodes: ObjNode[]) => {
			for (const n of nodes) {
				const matches = !treeFilter || nodeMatchesFilter(n, treeFilter);
				if (matches) out.push(n.prim_path);
				const isCollapsed = !treeFilter && collapsedNodes.has(n.prim_path);
				if (n.children?.length && (!isCollapsed || treeFilter)) {
					walk(n.children);
				}
			}
		};
		walk(objectInventory);
		return out;
	}
	const selectedObj = $derived(primarySelectedPath ? findNodeByPath(objectInventory, primarySelectedPath) : null);
	const selectedCount = $derived(selectedPaths.size);
	const selectedTargetPaths = $derived([...selectedPaths]);
	let cmdPending = $state<string | null>(null);
	let cmdMsg = $state('');
	let retryingJobId = $state<string | null>(null);
	let deletingJobId = $state<string | null>(null);
	let preparingBasicNow = $state(false);
	let viewMode = $state<ViewMode>('2d');
	let bottomTab = $state<BottomTabId>('jobs');
	let layerFilters = $state<Set<LayerKey>>(new Set(['scene', 'render', 'shape']));

	// Incident accordion + filter state
	let expandedIncidentId = $state<string | null>(null);
	let incidentFilter = $state<'all' | 'danger' | 'warning'>('all');

	// Unified job hub selection
	let selectedJobKey = $state<string | null>(null);

	let timer: ReturnType<typeof setInterval>;

	$effect(() => { currentSceneIdStore.set(currentSceneId); });
	$effect(() => { currentSceneStore.set(scene); });
	// When prepare_render_ready finishes, the daemon flips render_ready/shape_map_exists
	// on its scene record, but our SCENE_DETAIL_POLL_MS (7s) cycle leaves the gate
	// stale. Fire a forced getScene immediately on the running→idle transition.
	let prevPreparingNow = false;
	$effect(() => {
		const nowPreparing = preparingNow;
		if (prevPreparingNow && !nowPreparing) {
			lastSceneDetailAt = 0;
			lastJobsAt = 0;
			void refresh({ force: true });
		}
		prevPreparingNow = nowPreparing;
	});
	let refreshInFlight = false;
	let lastSceneDetailAt = 0;
	let lastJobsAt = 0;
	let lastInventoryAt = 0;
	let lastFloorplanAt = 0;
	let lastMatLibAt = 0;

	const SCENE_DETAIL_POLL_MS = 7000;
	const JOBS_POLL_MS = 5000;
	const INVENTORY_POLL_MS = 12000;
	const FLOORPLAN_POLL_MS = 15000;
	const MATLIB_POLL_MS = 30000;

	const isaacConnected = $derived($healthStore?.isaac_connected ?? false);
	const workerBusy = $derived($healthStore?.worker_state === 'running');
	const sessionConnected = $derived(!!session && !!isaacConnected);
	const shapeMapExists = $derived(!!scene?.shape_map_exists);
	const mitsubaSceneExists = $derived(!!scene?.mitsuba_scene_exists);
	const renderReady = $derived(!!scene?.render_ready);
	const activeCmd = $derived($healthStore?.active_isaac_command as Record<string, unknown> | null);
	const preparingNow = $derived(activeCmd?.command_type === 'prepare_render_ready');
	const prepareBasicDisabledReason = $derived(
		!currentSceneId
			? (L === 'kr' ? '씬이 선택되지 않음' : 'No scene selected')
		: preparingBasicNow
			? (L === 'kr' ? '생성 중…' : 'Already building…')
		: !scene?.mitsuba_scene_ref
			? (L === 'kr' ? 'Mitsuba XML 미등록 (scene_record.mitsuba_scene_ref 없음)' : 'Mitsuba XML not registered (missing scene_record.mitsuba_scene_ref)')
		: ''
		// If mitsuba_scene_exists is false we still enable — the backend probes
		// the XML directory for a sibling .xml and self-heals the stale catalog path.
	);
	const snapshotReady = $derived(
		!!scene?.scene_snapshot_ref
		|| !!scene?.shape_map_ref
		|| !!session?.scene_snapshot_ref
		|| !!session?.shape_map_ref
	);
	const renderDisabledReason = $derived(
		!sessionConnected ? (L === 'kr' ? '세션 연결 후 가능' : 'Connect session first')
		: preparingNow ? (L === 'kr' ? '준비 작업 진행 중…' : 'Prepare in progress…')
		: !mitsubaSceneExists && !shapeMapExists ? (L === 'kr' ? '준비 필요 (Mitsuba 씬 + Shape Map)' : 'Run Prepare (Mitsuba scene + Shape Map missing)')
		: !mitsubaSceneExists ? (L === 'kr' ? 'Mitsuba 씬 미생성 — 준비 재실행' : 'Mitsuba scene missing — re-run Prepare')
		: !shapeMapExists ? (L === 'kr' ? 'Shape Map 진행 중 — 잠시 후 다시' : 'Shape Map in progress — try again shortly')
		: workerBusy ? (L === 'kr' ? '워커가 작업 중' : 'Worker busy')
		: cmdPending ? (L === 'kr' ? '명령 진행 중' : 'Command in flight')
		: ''
	);

	type Tip = { title: string; text: string };

	const bp3dPrepareTip = $derived.by((): Tip => {
		const KR = L === 'kr';
		if (!sessionConnected)
			return KR
				? { title: '먼저 세션 연결이 필요해요', text: 'Isaac Sim 세션이 활성화돼야 3D 블루프린트용 snapshot 과 Shape Map 을 만들 수 있어요.' }
				: { title: 'Connect session first', text: 'An active Isaac session is required to build the 3D blueprint snapshot + Shape Map.' };
		if (preparingNow)
			return KR
				? { title: '장면 준비 중', text: '백그라운드에서 snapshot/Shape Map 빌드가 진행 중이에요. 큰 씬은 몇 분 걸릴 수 있어요.' }
				: { title: 'Preparing scene', text: 'Snapshot / Shape Map build is running in the background. Large scenes can take a few minutes.' };
		if (cmdPending)
			return KR
				? { title: '잠시만요', text: '다른 명령이 진행 중이에요. 끝나면 다시 활성화돼요.' }
				: { title: 'Hold on', text: 'Another command is running. The button will re-enable when it finishes.' };
		if (mitsubaSceneExists && shapeMapExists)
			return KR
				? { title: '재생성', text: '이미 준비된 상태지만, 씬이 변경됐다면 다시 실행해서 최신 snapshot 을 만들 수 있어요.' }
				: { title: 'Re-run', text: 'Already prepared — re-run if the scene changed to refresh the snapshot.' };
		return KR
			? {
					title: '3D 블루프린트 준비',
					text: 'Isaac Sim 씬에서 snapshot 과 Shape Map 을 추출해 3D 블루프린트와 렌더가 모두 가능하게 만듭니다.'
				}
			: {
					title: 'Prepare 3D blueprint',
					text: 'Extract snapshot + Shape Map from the Isaac scene so both blueprint and render can use them.'
				};
	});
	const isVisible = $derived($page.url.pathname.startsWith('/current-scene'));

	const cleanJobs = $derived(recentJobs.filter(j => String(j.job_id ?? '').trim()));
	const failedJobsCount = $derived(cleanJobs.filter(j => j.status === 'failed').length);
	const runningJobsCount = $derived(cleanJobs.filter(j => j.status === 'running').length);
	const queuedJobsCount = $derived(cleanJobs.filter(j => j.status === 'queued').length);
	const finishedJobsCount = $derived(cleanJobs.filter(j => j.status === 'succeeded' || j.status === 'failed').length);
	const runningCount = $derived((activeCmd ? 1 : 0) + runningJobsCount);
	const lastSucceededJob = $derived(cleanJobs.find(j => j.status === 'succeeded') ?? null);
	const bottomTabs = $derived<TabItem[]>([
		{ id: 'jobs', label: L === 'kr' ? '작업 큐' : 'Jobs', badge: runningCount > 0 ? runningCount : undefined },
		{ id: 'logs', label: L === 'kr' ? '최근 로그' : 'Logs', badge: $debugEvents.length > 0 ? $debugEvents.length : undefined },
		{ id: 'selection', label: L === 'kr' ? '선택 상세' : 'Selection', disabled: !selectedObj },
		{ id: 'history', label: L === 'kr' ? '렌더 이력' : 'History', badge: finishedJobsCount > 0 ? finishedJobsCount : undefined },
		{ id: 'materials', label: L === 'kr' ? '재질' : 'Materials' }
	]);

	const cameraCount = $derived(Number((scene as Record<string, unknown> | null)?.camera_count ?? 0));
	const meshCount = $derived(Number((scene as Record<string, unknown> | null)?.mesh_count ?? 0));
	const robotCount = $derived(((floorplan as Record<string, unknown> | null)?.robot_overlays as unknown[] | undefined)?.length ?? 0);
	const sessionOpenedAt = $derived(session ? String((session as Record<string, unknown>).opened_at ?? '') : '');
	const renderableObjectCount = $derived((() => {
		function count(nodes: ObjNode[]): number {
			let n = 0;
			for (const node of nodes) {
				if (node.kind === 'mesh') n += 1;
				if (node.children?.length) n += count(node.children);
			}
			return n;
		}
		return count(objectInventory);
	})());
	const materialCount = $derived(matGroups.reduce((acc, g) => acc + g.materials.length, 0));

	type CommandStep = { key: string; en: string; kr: string };

	// Stages for Isaac commands. Keep these in sync with render_daemon.py telemetry stages.
	const ISAAC_STAGES: Record<string, CommandStep[]> = {
		load_scene: [
			{ key: 'picked_up', en: 'Resolve Path', kr: '경로 해석' },
			{ key: 'resolving_scene', en: 'Open Stage', kr: 'stage 열기' },
			{ key: 'opening_stage', en: 'Load Assets', kr: '에셋 로딩' },
			{ key: 'assets_loading', en: 'Stream', kr: 'streaming' },
			{ key: 'assets_loaded', en: 'Hydra', kr: 'Hydra' },
			{ key: 'streaming_scene', en: 'Ready', kr: '준비 완료' }
		],
		prepare_render_ready: [
			{ key: 'picked_up', en: 'Inspect', kr: '검사' },
			{ key: 'collecting_scene_refs', en: 'Collect Refs', kr: 'ref 수집' },
			{ key: 'staging_scene', en: 'Stage XML', kr: 'XML 준비' },
			{ key: 'loading_scene', en: 'GPU Cache', kr: 'GPU 캐시' },
			{ key: 'ready', en: 'Ready', kr: '완료' }
		],
		connect_session: [
			{ key: 'picked_up', en: 'Collect Refs', kr: 'ref 수집' },
			{ key: 'collecting_scene_refs', en: 'Open Session', kr: '세션 열기' },
			{ key: 'opening_session', en: 'Register View', kr: '뷰 등록' },
			{ key: 'ready', en: 'Ready', kr: '완료' }
		],
		sync_session: [
			{ key: 'picked_up', en: 'Start', kr: '시작' },
			{ key: 'capturing_stage_state', en: 'Capture State', kr: '상태 수집' },
			{ key: 'serializing_patch', en: 'Serialize Patch', kr: 'patch 직렬화' },
			{ key: 'uploading_patch', en: 'Upload Patch', kr: 'patch 업로드' },
			{ key: 'syncing_viewport_camera', en: 'Sync Camera', kr: '카메라 동기화' },
			{ key: 'ready', en: 'Synced', kr: '동기화 완료' }
		],
		render_current_view: [
			{ key: 'picked_up', en: 'Start', kr: '시작' },
			{ key: 'ensuring_session', en: 'Session', kr: '세션 확인' },
			{ key: 'capturing_view', en: 'Capture View', kr: '뷰포트 수집' },
			{ key: 'sending_capture_request', en: 'Submit', kr: '요청 제출' },
			{ key: 'ambient', en: 'Ambient', kr: 'ambient' },
			{ key: 'staging_scene', en: 'Stage XML', kr: 'XML 준비' },
			{ key: 'loading_scene', en: 'Load GPU', kr: 'GPU 로딩' },
			{ key: 'rendering', en: 'Trace', kr: '렌더링' },
			{ key: 'saving_output', en: 'Save', kr: '저장' },
			{ key: 'active', en: 'Active', kr: 'active' },
			{ key: 'polar', en: 'Polar', kr: 'polar' },
			{ key: 'writing_manifest', en: 'Manifest', kr: 'manifest' }
		],
		render_sensor: [
			{ key: 'picked_up', en: 'Start', kr: '시작' },
			{ key: 'ensuring_session', en: 'Session', kr: '세션 확인' },
			{ key: 'resolving_sensor', en: 'Sensor', kr: '센서 확인' },
			{ key: 'sending_capture_request', en: 'Submit', kr: '요청 제출' },
			{ key: 'ambient', en: 'Ambient', kr: 'ambient' },
			{ key: 'staging_scene', en: 'Stage XML', kr: 'XML 준비' },
			{ key: 'loading_scene', en: 'Load GPU', kr: 'GPU 로딩' },
			{ key: 'rendering', en: 'Trace', kr: '렌더링' },
			{ key: 'saving_output', en: 'Save', kr: '저장' },
			{ key: 'active', en: 'Active', kr: 'active' },
			{ key: 'polar', en: 'Polar', kr: 'polar' },
			{ key: 'writing_manifest', en: 'Manifest', kr: 'manifest' }
		]
	};

	// Filtered presets
	const filteredPresets = $derived(presets.filter(p => {
		const q = matSearch.toLowerCase();
		return !q || p.title_en.toLowerCase().includes(q) || (p.title_kr ?? '').toLowerCase().includes(q);
	}));

	// Filtered dataset groups
	const filteredGroups = $derived(matGroups
		.filter(g => activeCategory === 'all' || g.dataset_id === 'curated')
		.map(g => ({
			...g,
			materials: g.materials.filter(m => {
				const q = matSearch.toLowerCase();
				const matchSearch = !q || m.display_name.toLowerCase().includes(q) || m.material_id.toLowerCase().includes(q);
				const matchCap = matCapFilter === 'all'
					|| (matCapFilter === 'polarized' && g.capabilities.polarization)
					|| (matCapFilter === 'nir' && g.capabilities.nir)
					|| (matCapFilter === 'available' && m.status === 'available');
				const matchCategory = activeCategory === 'all' || m.category === activeCategory;
				return matchSearch && matchCap && matchCategory;
			})
		}))
		.filter(g => g.materials.length > 0));

	const selectionKv = $derived<KeyValueItem[]>(
		selectedObj
			? [
				{ key: L === 'kr' ? '경로' : 'Path', value: selectedObj.prim_path, mono: true },
				{ key: L === 'kr' ? '종류' : 'Kind', value: selectedObj.kind ?? '—' },
				{ key: L === 'kr' ? '보임' : 'Visible', value: selectedObj.visible !== false ? '✓' : '✗', tone: selectedObj.visible === false ? 'warning' : 'success' },
				{ key: L === 'kr' ? '재정의' : 'Override', value: selectedObj.has_override ? (L === 'kr' ? '있음' : 'yes') : '—', tone: selectedObj.has_override ? 'active' : 'neutral' }
			]
			: []
	);

	const breadcrumbItems = $derived<BreadcrumbItem[]>(
		selectedObj
			? selectedObj.prim_path.split('/').filter(Boolean).map(p => ({ label: p }))
			: []
	);

	function buildSceneInfoKv(): KeyValueItem[] {
		const items: KeyValueItem[] = [];
		items.push({ key: 'Scene ID', value: currentSceneId ?? '—', mono: true });
		if (session) {
			const sess = session as Record<string, unknown>;
			items.push({ key: L === 'kr' ? '리비전' : 'Revision', value: String(sess.session_revision ?? '—') });
			items.push({ key: L === 'kr' ? '동기화' : 'Sync', value: sess.state_dirty ? '⚠ dirty' : '✓ clean', tone: sess.state_dirty ? 'warning' : 'success' });
		}
		if (scene) {
			const s = scene as Record<string, unknown>;
			if (s.usd_stage_path) items.push({ key: 'USD', value: String(s.usd_stage_path), mono: true });
			items.push({ key: L === 'kr' ? '마지막 업데이트' : 'Last Update', value: sessionOpenedAt ? `${ago(sessionOpenedAt)} ago` : '—' });
		}
		items.push({ key: L === 'kr' ? '카메라' : 'Cameras', value: String(cameraCount) });
		items.push({ key: L === 'kr' ? '메시' : 'Meshes', value: String(meshCount) });
		items.push({ key: L === 'kr' ? '로봇' : 'Robots', value: String(robotCount) });
		items.push({ key: L === 'kr' ? '렌더 가능 오브젝트' : 'Renderable', value: String(renderableObjectCount) });
		items.push({ key: L === 'kr' ? '재질 수' : 'Materials', value: String(materialCount) });
		if (lastSucceededJob?.finished_at) {
			items.push({ key: L === 'kr' ? '마지막 성공' : 'Last success', value: `${ago(String(lastSucceededJob.finished_at))} ago`, mono: true });
		}
		return items;
	}

	const sceneInfoKv = $derived<KeyValueItem[]>(buildSceneInfoKv());

	const recentLogs = $derived<LogEntry[]>(
		$debugEvents.map(ev => ({
			ts: ev.ts,
			level: ev.kind === 'error' ? 'error' : 'info',
			message: ev.message,
			source: ev.kind
		}))
	);

	type IncidentItem = {
		key: string;
		tone: Tone;
		title: string;
		description?: string;
		source?: string;
		timestamp?: string;
		jobId: string;
		fullError?: string;
		relatedJobs?: string[];
	};

	function truncate(s: string, n: number): string {
		return s.length > n ? s.slice(0, n - 1) + '…' : s;
	}

	const incidentItems = $derived<IncidentItem[]>((() => {
		const failed = recentJobs.filter(j => j.status === 'failed' && String(j.job_id ?? '').trim());
		// Group by identical error string (ignoring jobs without error text).
		const byKey = new Map<string, Record<string, unknown>[]>();
		for (const j of failed) {
			const err = j.error ? String(j.error) : '';
			const key = err || `__job__${String(j.job_id ?? '')}`;
			const bucket = byKey.get(key);
			if (bucket) bucket.push(j); else byKey.set(key, [j]);
		}
		const items: IncidentItem[] = [];
		for (const [, jobs] of byKey) {
			const rep = jobs[0];
			const jobId = String(rep.job_id ?? '');
			const err = rep.error ? String(rep.error) : '';
			const dup = jobs.length > 1 ? ` (${L === 'kr' ? '동일 오류' : 'same error'} ×${jobs.length})` : '';
			const descBase = rep.progress_stage ? String(rep.progress_stage).replace(/_/g, ' ') : '';
			items.push({
				key: jobId,
				tone: 'danger' as const,
				title: (L === 'kr' ? `렌더 실패 — ${jobId.slice(0, 12)}` : `Render failed — ${jobId.slice(0, 12)}`) + dup,
				description: (descBase || err) ? truncate(err || descBase, 80) : undefined,
				source: rep.scene_id ? String(rep.scene_id) : undefined,
				timestamp: rep.finished_at ? String(rep.finished_at) : undefined,
				jobId,
				fullError: err || undefined,
				relatedJobs: jobs.length > 1 ? jobs.slice(1).map(j => String(j.job_id ?? '')) : undefined
			});
			if (items.length >= 10) break;
		}
		return items;
	})());

	const visibleIncidents = $derived<IncidentItem[]>(
		incidentItems.filter(i => incidentFilter === 'all' || i.tone === incidentFilter)
	);

	function jumpToJobsTab() {
		bottomTab = 'jobs';
		if ($bottomPanelCollapsed) toggleBottomPanel();
	}

	type PipelineState = 'done' | 'running' | 'failed' | 'waiting';
	type PipelineStep = {
		key: string;
		label_en: string;
		label_kr: string;
		state: PipelineState;
		hint?: string;
	};

	function buildPipelineSteps(): PipelineStep[] {
		const isaacOk = isaacConnected;
		const sessOk = sessionConnected;
		const usdReady = !!scene?.mitsuba_scene_exists || !!scene?.usd_stage_path;
		const shapeMapReady = !!scene?.shape_map_exists || !!scene?.render_ready;
		const sceneReady = !!scene?.render_ready;
		const lastJob = recentJobs[0] as Record<string, unknown> | undefined;
		const lastJobStage = String(lastJob?.progress_stage ?? '');
		const lastJobStatus = String(lastJob?.status ?? '');
		const failedRecent = !!lastJob && lastJobStatus === 'failed';
		const lastSuccess = lastSucceededJob as Record<string, unknown> | null;

		function mark(done: boolean, running = false, failed = false): PipelineState {
			if (failed) return 'failed';
			if (done) return 'done';
			if (running) return 'running';
			return 'waiting';
		}

		return [
			{ key: 'isaac_connect', label_en: 'Isaac Connect', label_kr: 'Isaac 연결',
				state: mark(isaacOk, !isaacOk && cmdPending === 'connect_session'),
				hint: isaacOk ? 'connected' : 'idle' },
			{ key: 'usd_export', label_en: 'USD Export', label_kr: 'USD 내보내기',
				state: mark(usdReady) },
			{ key: 'shape_map', label_en: 'Shape Map', label_kr: 'Shape Map',
				state: mark(shapeMapReady, !!currentSceneId && !shapeMapReady) },
			{ key: 'material_meta', label_en: 'Material Meta', label_kr: '재질 메타',
				state: mark(matGroups.length > 0) },
			{ key: 'pose_sync', label_en: 'Pose Sync', label_kr: 'Pose 동기화',
				state: mark(sessOk && !((session as Record<string, unknown> | null)?.state_dirty)) },
			{ key: 'render_request', label_en: 'Render Request', label_kr: '렌더 요청',
				state: mark(!!lastJob, lastJobStatus === 'queued') },
			{ key: 'mitsuba_render', label_en: 'Mitsuba Render', label_kr: 'Mitsuba 렌더',
				state: mark(!!lastSuccess, lastJobStatus === 'running' && stageIndex(lastJobStage) >= STAGE_ORDER['rendering'], failedRecent),
				hint: lastJobStatus === 'running' ? lastJobStage.replace(/_/g, ' ') : undefined },
			{ key: 'capture_attach', label_en: 'Capture Attach', label_kr: 'Capture Attach',
				state: mark(sceneReady) }
		];
	}

	const pipelineSteps = $derived<PipelineStep[]>(buildPipelineSteps());

	function pipelineDot(state: PipelineState): string {
		if (state === 'done') return 'success';
		if (state === 'running') return 'active';
		if (state === 'failed') return 'danger';
		return 'neutral';
	}
	function pipelineGlyph(state: PipelineState): string {
		if (state === 'done') return '✓';
		if (state === 'running') return '⟳';
		if (state === 'failed') return '✕';
		return '·';
	}

	const jobColumns: DataTableColumn<JobRow>[] = [
		{ key: 'job_id', label: 'Job', mono: true, width: '11rem' },
		{ key: 'status', label: 'Status', width: '6rem' },
		{ key: 'stage', label: 'Stage', width: '8rem' },
		{ key: 'scene_id', label: 'Scene', mono: true },
		{ key: 'finished_at', label: 'Updated', width: '6rem', align: 'right' }
	];

	const jobRows = $derived<JobRow[]>(
		recentJobs
			.filter(j => String(j.job_id ?? '').trim())
			.slice(0, 30)
			.map(j => ({
				job_id: String(j.job_id ?? '').slice(0, 18),
				status: String(j.status ?? ''),
				stage: String(j.progress_stage ?? '—').replace(/_/g, ' '),
				scene_id: String(j.scene_id ?? ''),
				finished_at: j.finished_at ? `${ago(String(j.finished_at))} ago` : (j.status === 'running' ? '…' : '—')
			}))
	);

	type JobListRow = {
		key: string;              // job_id or '__isaac__'
		kind: 'isaac' | 'render';
		title: string;
		status: string;
		stage: string;
		source: Record<string, unknown>;
	};

	const ISAAC_JOB_KEY = '__isaac_active__';

	function isaacRowKey(cmd: Record<string, unknown>): string {
		const cid = String(cmd.command_id ?? '').trim();
		return cid ? `isaac:${cid}` : ISAAC_JOB_KEY;
	}

	const ISAAC_HISTORY_CAP = 30;
	const jobListGroups = $derived<{ labelKey: 'running' | 'queued' | 'recent' | 'failed'; label: string; rows: JobListRow[] }[]>((() => {
		const rows: JobListRow[] = [];
		const seenIsaacIds = new Set<string>();
		const isaacEntries: Record<string, unknown>[] = [];
		if (activeCmd) isaacEntries.push(activeCmd as Record<string, unknown>);
		const history = recentIsaacCommands.slice(0, ISAAC_HISTORY_CAP);
		for (const c of history) isaacEntries.push(c);
		for (const cmd of isaacEntries) {
			const key = isaacRowKey(cmd);
			if (seenIsaacIds.has(key)) continue;
			seenIsaacIds.add(key);
			const raw = String(cmd.status ?? '');
			const normalized = raw === 'completed' ? 'succeeded'
				: raw === 'dispatched' ? 'running'
				: raw;
			rows.push({
				key,
				kind: 'isaac',
				title: `Isaac: ${commandTypeLabel(String(cmd.command_type ?? ''), L as 'kr' | 'en')}`,
				status: normalized,
				stage: String(cmd.progress_stage ?? ''),
				source: cmd
			});
		}
		for (const j of recentJobs) {
			const jobId = String(j.job_id ?? '').trim();
			if (!jobId) continue;
			rows.push({
				key: jobId,
				kind: 'render',
				title: jobId.slice(0, 18),
				status: String(j.status ?? ''),
				stage: String(j.progress_stage ?? ''),
				source: j as Record<string, unknown>
			});
		}
		const groups: { labelKey: 'running' | 'queued' | 'recent' | 'failed'; label: string; rows: JobListRow[] }[] = [
			{ labelKey: 'running', label: L === 'kr' ? '실행 중' : 'Running', rows: rows.filter(r => r.status === 'running') },
			{ labelKey: 'queued',  label: L === 'kr' ? '대기' : 'Queued',    rows: rows.filter(r => r.status === 'queued') },
			{ labelKey: 'recent',  label: L === 'kr' ? '최근 완료' : 'Recently completed', rows: rows.filter(r => r.status === 'succeeded').slice(0, 8) },
			{ labelKey: 'failed',  label: L === 'kr' ? '실패' : 'Failed',    rows: rows.filter(r => r.status === 'failed').slice(0, 8) }
		];
		return groups.filter(g => g.rows.length > 0);
	})());

	$effect(() => {
		// Auto-select the first running job if nothing is selected, or if the current selection vanished.
		const allKeys = new Set(jobListGroups.flatMap(g => g.rows.map(r => r.key)));
		if (selectedJobKey && !allKeys.has(selectedJobKey)) selectedJobKey = null;
		if (!selectedJobKey) {
			const running = jobListGroups.find(g => g.labelKey === 'running')?.rows[0];
			if (running) selectedJobKey = running.key;
		}
	});

	function toggleLayer(layer: LayerKey) {
		const next = new Set(layerFilters);
		if (next.has(layer)) next.delete(layer); else next.add(layer);
		layerFilters = next;
	}

	function autoSwitchToSelection() {
		if (selectedObj) bottomTab = 'selection';
	}

	async function loadFloorplan(sceneId: string) {
		try {
			const data = await fetch(`/api/scenes/${encodeURIComponent(sceneId)}/floorplan`).then(r => r.json());
			floorplan = data;
			floorplanImgSrc = (data.artifact_href as string) ?? ((data.artifact_path as string) ? `/artifacts?path=${encodeURIComponent(String(data.artifact_path))}` : null);
			floorplanError = String(data.error ?? '');
		} catch (error: unknown) {
			floorplan = null;
			floorplanImgSrc = null;
			floorplanError = error instanceof Error ? error.message : 'Failed to load floorplan';
		}
	}

	function onFloorplanImageError() {
		floorplanImgSrc = null;
		floorplanError = L === 'kr' ? '2D 맵 이미지 파일을 불러오지 못했습니다.' : 'Failed to load the 2D map image.';
	}

	function clearCurrentSceneSocketRetry() {
		if (currentSceneSocketRetry != null) {
			clearTimeout(currentSceneSocketRetry);
			currentSceneSocketRetry = null;
		}
	}

	function disconnectCurrentSceneStream() {
		clearCurrentSceneSocketRetry();
		currentSceneSocketClosedByUs = true;
		if (currentSceneSocket) {
			try {
				currentSceneSocket.close();
			} catch {}
		}
		currentSceneSocket = null;
		currentSceneSocketSceneId = null;
	}

	function currentSceneStreamUrl(sceneId: string): string | null {
		if (typeof window === 'undefined') return null;
		const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
		return `${protocol}//${window.location.host}/api/ws/current-scene?scene_id=${encodeURIComponent(sceneId)}`;
	}

	function applyCurrentSceneTelemetry(message: unknown) {
		if (!message || typeof message !== 'object') return;
		const payload = message as LiveCameraPayload;
		if (payload.scene_id && currentSceneId && payload.scene_id !== currentSceneId) return;
		const activeCamera = payload.active_viewport_camera;
		liveActiveViewportCamera = activeCamera && typeof activeCamera === 'object' ? activeCamera : null;
		drawOverlays();
	}

	function scheduleCurrentSceneReconnect(sceneId: string) {
		if (!isVisible || !currentSceneId || currentSceneId !== sceneId) return;
		clearCurrentSceneSocketRetry();
		currentSceneSocketRetry = setTimeout(() => {
			currentSceneSocketRetry = null;
			connectCurrentSceneStream(sceneId);
		}, 1000);
	}

	function connectCurrentSceneStream(sceneId: string) {
		const url = currentSceneStreamUrl(sceneId);
		if (!url) return;
		if (
			currentSceneSocket &&
			currentSceneSocketSceneId === sceneId &&
			(currentSceneSocket.readyState === WebSocket.OPEN || currentSceneSocket.readyState === WebSocket.CONNECTING)
		) {
			return;
		}
		disconnectCurrentSceneStream();
		currentSceneSocketClosedByUs = false;
		const ws = new WebSocket(url);
		currentSceneSocket = ws;
		currentSceneSocketSceneId = sceneId;
		ws.onmessage = (event) => {
			try {
				applyCurrentSceneTelemetry(JSON.parse(String(event.data ?? '{}')));
			} catch {}
		};
		ws.onerror = () => {
			try {
				ws.close();
			} catch {}
		};
		ws.onclose = () => {
			if (currentSceneSocket === ws) {
				currentSceneSocket = null;
				currentSceneSocketSceneId = null;
			}
			if (!currentSceneSocketClosedByUs) {
				scheduleCurrentSceneReconnect(sceneId);
			}
		};
	}

	async function refresh(opts: { force?: boolean } = {}) {
		if (refreshInFlight) return;
		refreshInFlight = true;
		try {
			const now = Date.now();
			const force = !!opts.force;
			const [sumRes, sessRes] = await Promise.all([
				summary().catch(() => null),
				getIsaacSession().catch(() => null)
			]);
			const newSceneId: string | null = sumRes?.current_scene_id ?? null;
			const prevSceneId = currentSceneId;
			currentSceneId = newSceneId;
			session = sessRes?.status === 'active' ? (sessRes.session as Record<string, unknown>) : null;
			liveActiveViewportCamera = session
				? ((session as Record<string, unknown>).active_viewport_camera as Record<string, unknown> | null) ?? liveActiveViewportCamera
				: null;
			if (session) {
				const isaacSelected = ((session as Record<string, unknown>).selected_prim_paths as string[] | undefined) ?? [];
				applyExternalSelection(Array.isArray(isaacSelected) ? isaacSelected.map(String) : []);
			}

			if (newSceneId) {
				const sceneChanged = newSceneId !== prevSceneId;
				if (sceneChanged) {
					lastSceneDetailAt = 0;
					lastJobsAt = 0;
					lastInventoryAt = 0;
					lastFloorplanAt = 0;
					liveActiveViewportCamera = null;
				}

				const tasks: Promise<void>[] = [];
				if (force || sceneChanged || now - lastSceneDetailAt > SCENE_DETAIL_POLL_MS) {
					lastSceneDetailAt = now;
					tasks.push(getScene(newSceneId).then((sceneRes) => { scene = sceneRes; }).catch(() => {}));
				}
				if (force || sceneChanged || now - lastJobsAt > JOBS_POLL_MS) {
					lastJobsAt = now;
					tasks.push(listJobs(30).then(r => { recentJobs = r.jobs ?? []; }).catch(() => {}));
					tasks.push(listIsaacCommands().then(r => { recentIsaacCommands = r.commands ?? []; }).catch(() => {}));
				}
				if (sessRes?.status === 'active' && (force || sceneChanged || now - lastInventoryAt > INVENTORY_POLL_MS)) {
					lastInventoryAt = now;
					tasks.push(
						getIsaacSessionInventory()
							.then((invRes) => {
								objectInventory = buildObjectTree(invRes.object_inventory ?? []);
								initializeTreeForScene(newSceneId, objectInventory);
							})
							.catch(() => {})
					);
				}
				if (force || sceneChanged || now - lastFloorplanAt > FLOORPLAN_POLL_MS) {
					lastFloorplanAt = now;
					tasks.push(loadFloorplan(newSceneId));
				}
				if (force || now - lastMatLibAt > MATLIB_POLL_MS) {
					lastMatLibAt = now;
					tasks.push(
						materialLibrary()
							.then(r => { matGroups = (r.groups ?? matGroups) as DatasetGroup[]; })
							.catch(() => {})
					);
				}
				await Promise.all(tasks);
			} else {
				scene = null; recentJobs = []; recentIsaacCommands = []; objectInventory = [];
				floorplan = null; floorplanImgSrc = null;
				floorplanError = '';
				liveActiveViewportCamera = null;
				collapsedNodes = new Set();
				treeInitializedSceneId = null;
			}
		} catch {
		} finally {
			loading = false;
			refreshInFlight = false;
		}
	}

	onMount(async () => {
		try {
			const [presRes, libRes, scenesRes] = await Promise.all([
				materialPresets().then(r => r.presets ?? []).catch(() => []),
				materialLibrary().then(r => r.groups ?? []).catch(() => []),
				listIsaacScenes().then(r => r.scenes ?? []).catch(() => [])
			]);
			presets = presRes;
			matGroups = libRes as DatasetGroup[];
			registeredScenes = scenesRes;
		} catch {}
		if (isVisible) await refresh();
		else loading = false;
		timer = setInterval(() => {
			if (isVisible) void refresh();
		}, 3000);
	});
	onDestroy(() => {
		clearInterval(timer);
		disconnectCurrentSceneStream();
		sceneRailSnippet.set(null);
		sceneBottomSnippet.set(null);
	});

	$effect(() => {
		if (!isVisible || !currentSceneId) {
			disconnectCurrentSceneStream();
			return;
		}
		connectCurrentSceneStream(currentSceneId);
		return () => {
			disconnectCurrentSceneStream();
		};
	});

	async function sendCommand(cmd: string, sceneId?: string) {
		const sid = sceneId ?? currentSceneId;
		if (cmdPending || !sid) return;
		cmdPending = cmd + (sceneId ?? '');
		cmdMsg = '';
		try {
			await isaacCommand(cmd, sid);
			cmdMsg = L === 'kr' ? `${cmd} 전송됨` : `${cmd} sent`;
			await refresh({ force: true });
		} catch (e: unknown) {
			cmdMsg = (e as Error).message ?? 'error';
		} finally { cmdPending = null; }
	}

	async function handleSmokeRender() {
		if (!currentSceneId || cmdPending) return;
		cmdPending = 'smoke';
		try {
			await smokeRender(currentSceneId);
			cmdMsg = L === 'kr' ? '스모크 렌더 전송됨' : 'Smoke queued';
		} catch (e: unknown) {
			cmdMsg = (e as Error).message ?? 'error';
		} finally { cmdPending = null; }
	}

	async function handlePrepareBasic() {
		if (!currentSceneId || preparingBasicNow) return;
		preparingBasicNow = true;
		try {
			const r = await prepareBasicScene(currentSceneId);
			cmdMsg = L === 'kr'
				? `기본 스냅샷 생성됨 · 메시 ${r.mesh_count} · 매칭 ${r.matched}/${r.shape_count}`
				: `Basic snapshot built · meshes ${r.mesh_count} · matched ${r.matched}/${r.shape_count}`;
			await refresh({ force: true });
		} catch (e: unknown) {
			cmdMsg = (e as Error).message ?? 'error';
		} finally { preparingBasicNow = false; }
	}

	async function applyPreset(preset: Preset) {
		if (!currentSceneId) return;
		try {
			await applyMeasuredMaterial(currentSceneId, { bsdf_type: preset.bsdf_type, prim_path: selectedObj?.prim_path });
			cmdMsg = L === 'kr' ? `재질 적용: ${preset.title_kr || preset.title_en}` : `Applied: ${preset.title_en}`;
		} catch (e: unknown) { cmdMsg = (e as Error).message ?? 'error'; }
	}

	async function applyMeasured(group: DatasetGroup, mat: MatEntry) {
		if (!currentSceneId || mat.status !== 'available') return;
		try {
			if (mat.kind === 'curated') {
				await applyCuratedMaterial(currentSceneId, {
					material_id: mat.material_id,
					prim_path: selectedObj?.prim_path
				});
			} else {
				await applyMeasuredMaterial(currentSceneId, {
					dataset_id: group.dataset_id,
					material_id: mat.material_id,
					measured_file_path: mat.native_file,
					mitsuba_strategy: group.mitsuba_strategy,
					prim_path: selectedObj?.prim_path
				});
			}
			cmdMsg = L === 'kr' ? `재질 적용: ${mat.display_name}` : `Applied: ${mat.display_name}`;
		} catch (e: unknown) { cmdMsg = (e as Error).message ?? 'error'; }
	}

	async function startDownload(datasetId: string) {
		// hpBRDF files are ~13 GB each (182 GB total) — guard against accidental clicks.
		if (datasetId === 'hpbrdf_2025') {
			const grp = matGroups.find(g => g.dataset_id === datasetId);
			const pending = grp?.materials.filter(m => m.status === 'not_downloaded' && m.download_url).length ?? 0;
			if (pending > 0) {
				const totalGb = pending * 13;
				const msg = L === 'kr'
					? `hpBRDF 데이터셋은 파일 1개당 약 13 GB 입니다.\n${pending}개 파일 다운로드 (총 ~${totalGb} GB).\n계속할까요?`
					: `hpBRDF files are ~13 GB each.\nDownloading ${pending} file(s) (total ~${totalGb} GB).\nContinue?`;
				if (!confirm(msg)) return;
			}
		}
		try {
			const r = await downloadDataset(datasetId);
			if (r.job_id) {
				dlJobs[datasetId] = { done: 0, total: 0, status: 'running' };
				dlJobs = { ...dlJobs };
				pollDownload(datasetId, r.job_id);
			} else {
				cmdMsg = L === 'kr' ? '다운로드할 항목 없음' : 'Nothing to download';
			}
		} catch (e: unknown) { cmdMsg = (e as Error).message ?? 'error'; }
	}

	async function pollDownload(datasetId: string, jobId: string) {
		try {
			const r = await getDatasetDownloadStatus(jobId);
			dlJobs[datasetId] = r;
			dlJobs = { ...dlJobs };
			if (r.status !== 'done') {
				setTimeout(() => pollDownload(datasetId, jobId), 1500);
			} else {
				const lib = await materialLibrary().catch(() => null);
				if (lib) matGroups = lib.groups ?? matGroups;
			}
		} catch {}
	}

	async function handleRetry(jobId: string) {
		if (retryingJobId) return;
		retryingJobId = jobId;
		try {
			await retryJob(jobId);
			cmdMsg = L === 'kr' ? `재시도 전송: ${jobId.slice(0, 12)}` : `Retry queued: ${jobId.slice(0, 12)}`;
			await refresh();
		} catch (e: unknown) {
			cmdMsg = (e as Error).message ?? 'error';
		} finally { retryingJobId = null; }
	}

	async function handleDeleteJob(jobId: string, currentStatus: string) {
		if (!jobId || deletingJobId) return;
		const isActive = currentStatus === 'running' || currentStatus === 'queued';
		deletingJobId = jobId;
		try {
			await deleteJob(jobId, { force: isActive });
			if (selectedJobKey === jobId) selectedJobKey = null;
			cmdMsg = L === 'kr' ? `삭제됨: ${jobId.slice(0, 12)}` : `Deleted: ${jobId.slice(0, 12)}`;
			await refresh({ force: true });
		} catch (e: unknown) {
			cmdMsg = (e as Error).message ?? 'error';
		} finally { deletingJobId = null; }
	}

	function toggleGroup(datasetId: string) {
		const next = new Set(collapsedGroups);
		if (next.has(datasetId)) next.delete(datasetId); else next.add(datasetId);
		collapsedGroups = next;
	}

	function flatTree(nodes: ObjNode[]): ObjNode[] {
		const out: ObjNode[] = [];
		for (const n of nodes) { out.push(n); if (n.children?.length) out.push(...flatTree(n.children)); }
		return out;
	}

	function normalizeInventoryNode(item: unknown): ObjNode | null {
		if (!item || typeof item !== 'object') return null;
		const raw = item as Record<string, unknown>;
		const primPath = String(raw.prim_path ?? raw.path ?? '');
		if (!primPath.startsWith('/')) return null;
		const fallbackName = primPath.split('/').filter(Boolean).pop() ?? primPath;
		const children = Array.isArray(raw.children)
			? raw.children.map(normalizeInventoryNode).filter((node): node is ObjNode => !!node)
			: undefined;
		const overrideBsdf = raw.override_bsdf ?? raw.bsdf_override;
		return {
			prim_path: primPath,
			name: String(raw.name ?? fallbackName),
			kind: String(raw.kind ?? (children?.length ? 'group' : 'object')),
			children,
			visible: typeof raw.visible === 'boolean' ? raw.visible : null,
			has_override: Boolean(raw.has_override ?? overrideBsdf),
			selected: Boolean(raw.selected),
			shape_count: Number(raw.shape_count ?? 0)
		};
	}

	function buildObjectTree(items: unknown): ObjNode[] {
		if (!Array.isArray(items)) return [];
		const normalized = items
			.map(normalizeInventoryNode)
			.filter((node): node is ObjNode => !!node);
		if (normalized.some((node) => node.children?.length)) return normalized;

		const byPath = new Map<string, ObjNode>();
		for (const node of normalized) {
			byPath.set(node.prim_path, { ...node, children: [] });
		}
		for (const node of normalized) {
			const parts = node.prim_path.split('/').filter(Boolean);
			let current = '';
			for (const part of parts.slice(0, -1)) {
				current += `/${part}`;
				if (!byPath.has(current)) {
					byPath.set(current, {
						prim_path: current,
						name: part,
						kind: 'group',
						children: [],
						visible: null,
						has_override: false,
						selected: false,
						shape_count: 0
					});
				}
			}
		}

		const roots: ObjNode[] = [];
		const sorted = [...byPath.values()].sort((a, b) => a.prim_path.localeCompare(b.prim_path));
		for (const node of sorted) {
			const parentPath = node.prim_path.split('/').filter(Boolean).slice(0, -1).join('/');
			const parent = parentPath ? byPath.get(`/${parentPath}`) : null;
			if (parent) {
				parent.children ??= [];
				if (!parent.children.some((child) => child.prim_path === node.prim_path)) {
					parent.children.push(node);
				}
			} else {
				roots.push(node);
			}
		}

		function sortChildren(nodes: ObjNode[]) {
			nodes.sort((a, b) => {
				const aGroup = a.children?.length ? 0 : 1;
				const bGroup = b.children?.length ? 0 : 1;
				return aGroup - bGroup || a.name.localeCompare(b.name);
			});
			for (const node of nodes) if (node.children?.length) sortChildren(node.children);
		}
		sortChildren(roots);
		return roots;
	}

	function defaultCollapsedNodes(nodes: ObjNode[], depth = 0, out = new Set<string>()): Set<string> {
		for (const node of nodes) {
			if (!node.children?.length) continue;
			if (depth > 0) out.add(node.prim_path);
			defaultCollapsedNodes(node.children, depth + 1, out);
		}
		return out;
	}

	function initializeTreeForScene(sceneId: string, nodes: ObjNode[]) {
		if (!nodes.length || treeInitializedSceneId === sceneId) return;
		collapsedNodes = defaultCollapsedNodes(nodes);
		treeInitializedSceneId = sceneId;
	}

	function toggleNode(primPath: string) {
		const next = new Set(collapsedNodes);
		if (next.has(primPath)) next.delete(primPath); else next.add(primPath);
		collapsedNodes = next;
	}

	function expandAllTree() {
		collapsedNodes = new Set();
	}

	function collapseTree() {
		collapsedNodes = defaultCollapsedNodes(objectInventory);
	}

	function nodeMatchesFilter(node: ObjNode, q: string): boolean {
		if (!q) return true;
		const lq = q.toLowerCase();
		if ((node.name ?? '').toLowerCase().includes(lq)) return true;
		if (node.prim_path.toLowerCase().includes(lq)) return true;
		return (node.children ?? []).some(c => nodeMatchesFilter(c, q));
	}

	const filteredTree = $derived(treeFilter
		? objectInventory.filter(n => nodeMatchesFilter(n, treeFilter))
		: objectInventory
	);

	const treeCount = $derived(flatTree(objectInventory).length);

	function selectObj(node: ObjNode, e?: MouseEvent | KeyboardEvent) {
		const isCtrl = !!(e && (e.ctrlKey || e.metaKey));
		const isShift = !!(e && e.shiftKey);
		const next = new Set(selectedPaths);
		if (isShift && selectionAnchorPath && selectionAnchorPath !== node.prim_path) {
			const visible = visibleFlatTreePaths();
			const i = visible.indexOf(selectionAnchorPath);
			const j = visible.indexOf(node.prim_path);
			if (i >= 0 && j >= 0) {
				const [lo, hi] = i <= j ? [i, j] : [j, i];
				for (let k = lo; k <= hi; k++) next.add(visible[k]);
			} else {
				next.add(node.prim_path);
			}
			primarySelectedPath = node.prim_path;
		} else if (isCtrl) {
			if (next.has(node.prim_path)) {
				next.delete(node.prim_path);
				if (primarySelectedPath === node.prim_path) {
					primarySelectedPath = next.size ? [...next][next.size - 1] : null;
				}
			} else {
				next.add(node.prim_path);
				primarySelectedPath = node.prim_path;
			}
			selectionAnchorPath = node.prim_path;
		} else {
			next.clear();
			next.add(node.prim_path);
			primarySelectedPath = node.prim_path;
			selectionAnchorPath = node.prim_path;
		}
		selectedPaths = next;
		lastUserSelectionEditMs = Date.now();
		lastExternalSelectionSignature = cmpSelectionFromState();
		drawOverlays();
	}

	function toggleObjSelection(node: ObjNode) {
		const next = new Set(selectedPaths);
		if (next.has(node.prim_path)) {
			next.delete(node.prim_path);
			if (primarySelectedPath === node.prim_path) {
				primarySelectedPath = next.size ? [...next][next.size - 1] : null;
			}
		} else {
			next.add(node.prim_path);
			primarySelectedPath = node.prim_path;
			selectionAnchorPath = node.prim_path;
		}
		selectedPaths = next;
		lastUserSelectionEditMs = Date.now();
		lastExternalSelectionSignature = cmpSelectionFromState();
		drawOverlays();
	}

	function clearSelection() {
		selectedPaths = new Set();
		primarySelectedPath = null;
		selectionAnchorPath = null;
		lastUserSelectionEditMs = Date.now();
		lastExternalSelectionSignature = '';
		drawOverlays();
	}

	function applyExternalSelection(paths: string[]) {
		const sig = cmpSelectionSignature(paths);
		if (sig === lastExternalSelectionSignature) return;
		lastExternalSelectionSignature = sig;
		// Suppress remote replays of our own click for 500ms.
		if (Date.now() - lastUserSelectionEditMs < 500) return;
		const next = new Set(paths);
		selectedPaths = next;
		primarySelectedPath = paths.length ? paths[paths.length - 1] : null;
		selectionAnchorPath = primarySelectedPath;
		drawOverlays();
	}

	function onMapLoad() {
		if (!mapCanvas || !mapImg) return;
		mapCanvas.width = mapImg.naturalWidth || 512;
		mapCanvas.height = mapImg.naturalHeight || 512;
		drawOverlays();
	}

	function zoomBy(factor: number, cx?: number, cy?: number) {
		const next = Math.max(0.25, Math.min(8, mapZoom * factor));
		if (next === mapZoom) return;
		if (cx !== undefined && cy !== undefined && mapViewport) {
			const rect = mapViewport.getBoundingClientRect();
			const dx = cx - rect.left - rect.width / 2 - mapPanX;
			const dy = cy - rect.top - rect.height / 2 - mapPanY;
			const k = next / mapZoom - 1;
			mapPanX -= dx * k;
			mapPanY -= dy * k;
		}
		mapZoom = next;
	}

	function resetMapView() {
		mapZoom = 1;
		mapPanX = 0;
		mapPanY = 0;
	}

	function onMapWheel(e: WheelEvent) {
		e.preventDefault();
		const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
		zoomBy(factor, e.clientX, e.clientY);
	}

	function onMapPointerDown(e: PointerEvent) {
		if (e.button !== 0) return;
		e.preventDefault();
		isPanning = true;
		panStart = { x: e.clientX, y: e.clientY, px: mapPanX, py: mapPanY };
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	}

	function onMapPointerMove(e: PointerEvent) {
		if (!isPanning) return;
		mapPanX = panStart.px + (e.clientX - panStart.x);
		mapPanY = panStart.py + (e.clientY - panStart.y);
	}

	function onMapPointerUp(e: PointerEvent) {
		if (!isPanning) return;
		isPanning = false;
		try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
	}

	function drawOverlays() {
		if (!mapCanvas || !floorplan) return;
		const fp = floorplan as Record<string, unknown>;
		const canvasSize = (fp.canvas_size_px as number) ?? 512;
		const ctx = mapCanvas.getContext('2d');
		if (!ctx) return;
		const canvasWidth = mapCanvas.width;
		const canvasHeight = mapCanvas.height;
		const scaleX = canvasWidth / canvasSize;
		const scaleY = canvasHeight / canvasSize;
		ctx.clearRect(0, 0, canvasWidth, canvasHeight);
		const mirrorCanvasX = (value: number) => canvasWidth - value;

		function projectWorld(position: unknown): [number, number] | null {
			if (!Array.isArray(position) || position.length < 3) return null;
			const bounds = fp.world_bounds_xz as Record<string, number> | undefined;
			const projection = fp.projection as Record<string, number> | undefined;
			if (!bounds || !projection) return null;
			const x = Number(position[0]);
			const z = Number(position[2]);
			if (!Number.isFinite(x) || !Number.isFinite(z)) return null;
			return [
				(x - Number(bounds.x_min)) * Number(projection.scale_px_per_world_unit) + Number(projection.pad_x),
				(Number(bounds.z_max) - z) * Number(projection.scale_px_per_world_unit) + Number(projection.pad_z)
			];
		}

		function overlayPoint(item: Record<string, unknown>, fallbackWorldKey = 'origin'): [number, number] | null {
			const canvasX = Number(item.canvas_x);
			const canvasY = Number(item.canvas_y);
			if (Number.isFinite(canvasX) && Number.isFinite(canvasY)) return [canvasX, canvasY];
			const centroid = item.centroid_px;
			if (Array.isArray(centroid) && centroid.length >= 2) {
				const x = Number(centroid[0]);
				const y = Number(centroid[1]);
				if (Number.isFinite(x) && Number.isFinite(y)) return [x, y];
			}
			return projectWorld(item[fallbackWorldKey]);
		}

		const sceneLayer = layerFilters.has('scene');
		const baseCams = sceneLayer ? ((fp.camera_overlays as Record<string,unknown>[]) ?? []) : [];
		const cams = baseCams.filter((cam) => String(cam.kind ?? '') !== 'active_viewport');
		const fallbackActiveCamera = fp.active_viewport_camera;
		const activeCamera = liveActiveViewportCamera ?? (fallbackActiveCamera && typeof fallbackActiveCamera === 'object' ? fallbackActiveCamera as Record<string, unknown> : null);
		if (sceneLayer && activeCamera) {
			cams.unshift({
				...activeCamera,
				camera_id: String(activeCamera.sensor_id ?? activeCamera.camera_id ?? 'active_viewport'),
				label: String(activeCamera.name ?? activeCamera.label ?? activeCamera.sensor_id ?? 'Active viewport'),
				kind: 'active_viewport'
			});
		}
		for (const cam of cams) {
			const point = overlayPoint(cam, 'origin');
			if (!point) continue;
			const x = mirrorCanvasX(point[0] * scaleX);
			const y = point[1] * scaleY;
			const targetPoint = projectWorld(cam.target);
			const kind = String(cam.kind ?? '');
			const isActive = kind === 'active_viewport';
			const isRequest = kind === 'request' || cam.request === true;
			const color = isActive ? '47,123,246' : isRequest ? '230,126,34' : '22,163,74';
			if (targetPoint) {
				const tx = mirrorCanvasX(targetPoint[0] * scaleX);
				const ty = targetPoint[1] * scaleY;
				const dx = tx - x;
				const dy = ty - y;
				const length = Math.hypot(dx, dy);
				if (length > 0.001) {
					const ux = dx / length;
					const uy = dy / length;
					const fovDeg = Number(cam.fov_deg) || 60;
					const half = Math.min(Math.max(fovDeg * Math.PI / 360, Math.PI / 18), Math.PI * 0.48);
					const reach = Math.max(72 * scaleX, Math.min(length * 1.65, 190 * scaleX));
					const leftAngle = Math.atan2(uy, ux) - half;
					const rightAngle = Math.atan2(uy, ux) + half;
					const leftX = x + Math.cos(leftAngle) * reach;
					const leftY = y + Math.sin(leftAngle) * reach;
					const rightX = x + Math.cos(rightAngle) * reach;
					const rightY = y + Math.sin(rightAngle) * reach;

					ctx.fillStyle = `rgba(${color},${isActive ? 0.22 : 0.14})`;
					ctx.strokeStyle = `rgba(${color},${isActive ? 0.92 : 0.78})`;
					ctx.lineWidth = Math.max(2, isActive ? 3.5 * scaleX : 2.5 * scaleX);
					ctx.beginPath();
					ctx.moveTo(x, y);
					ctx.lineTo(leftX, leftY);
					ctx.arc(x, y, reach, leftAngle, rightAngle);
					ctx.closePath();
					ctx.fill();
					ctx.stroke();

					ctx.strokeStyle = `rgba(${color},0.95)`;
					ctx.lineWidth = Math.max(3, isActive ? 4 * scaleX : 3 * scaleX);
					ctx.beginPath();
					ctx.moveTo(x, y);
					ctx.lineTo(tx, ty);
					ctx.stroke();

					const headSize = Math.max(8, 10 * scaleX);
					const hx = x + ux * Math.min(length, reach);
					const hy = y + uy * Math.min(length, reach);
					ctx.fillStyle = `rgba(${color},0.98)`;
					ctx.beginPath();
					ctx.moveTo(hx, hy);
					ctx.lineTo(hx - ux * headSize - uy * headSize * 0.55, hy - uy * headSize + ux * headSize * 0.55);
					ctx.lineTo(hx - ux * headSize + uy * headSize * 0.55, hy - uy * headSize - ux * headSize * 0.55);
					ctx.closePath();
					ctx.fill();
				}
			}
			const radius = (isActive ? 10 : 8) * scaleX;
			ctx.fillStyle = 'rgba(255,255,255,0.92)';
			ctx.strokeStyle = `rgba(${color},1)`;
			ctx.lineWidth = Math.max(2, 2.5 * scaleX);
			ctx.beginPath(); ctx.arc(x, y, radius + 2 * scaleX, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
			ctx.fillStyle = `rgba(${color},0.98)`;
			ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill();
			ctx.fillStyle = 'white';
			ctx.font = `bold ${Math.max(9, 10 * scaleX)}px sans-serif`;
			ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
			ctx.fillText('C', x, y + 0.5 * scaleX);
			ctx.textAlign = 'start'; ctx.textBaseline = 'alphabetic';
			const label = String(cam.label ?? cam.name ?? cam.camera_id ?? '');
			if (label) {
				const lx = x + (radius + 8 * scaleX);
				const ly = y - (radius + 7 * scaleX);
				ctx.font = `bold ${Math.max(10, 11 * scaleX)}px sans-serif`;
				const w = ctx.measureText(label).width;
				ctx.fillStyle = 'rgba(15,23,42,0.78)';
				ctx.strokeStyle = 'rgba(255,255,255,0.72)';
				ctx.lineWidth = 1;
				ctx.beginPath();
				ctx.roundRect(lx - 4 * scaleX, ly - 13 * scaleX, w + 8 * scaleX, 17 * scaleX, 4 * scaleX);
				ctx.fill();
				ctx.stroke();
				ctx.fillStyle = 'white';
				ctx.fillText(label, lx, ly);
			}
		}

		const robots = sceneLayer ? ((fp.robot_overlays as Record<string,unknown>[]) ?? []) : [];
		for (const rob of robots) {
			const point = overlayPoint(rob);
			if (!point) continue;
			const x = mirrorCanvasX(point[0] * scaleX);
			const y = point[1] * scaleY;
			ctx.fillStyle = 'rgba(245,158,11,0.95)';
			ctx.beginPath(); ctx.arc(x, y, 7 * scaleX, 0, Math.PI * 2); ctx.fill();
			ctx.fillStyle = 'white';
			ctx.font = `bold ${9 * scaleX}px sans-serif`;
			ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
			ctx.fillText('R', x, y);
			ctx.textAlign = 'start'; ctx.textBaseline = 'alphabetic';
		}

		if (selectedObj) {
			const objs = (fp.object_overlays as Record<string,unknown>[]) ?? [];
			for (const obj of objs) {
				if ((obj.prim_path ?? obj.path) !== selectedObj.prim_path) continue;
				const point = overlayPoint(obj);
				if (!point) continue;
				const x = mirrorCanvasX(point[0] * scaleX);
				const y = point[1] * scaleY;
				ctx.strokeStyle = '#dc2626';
				ctx.lineWidth = 2 * scaleX;
				ctx.beginPath(); ctx.arc(x, y, 10 * scaleX, 0, Math.PI * 2); ctx.stroke();
				ctx.fillStyle = 'rgba(220,38,38,0.15)';
				ctx.fill();
			}
		}
	}

	$effect(() => { selectedObj; layerFilters; floorplan; liveActiveViewportCamera; drawOverlays(); });

	function statusClass(s: string) {
		if (s === 'succeeded') return 'badge-succeeded';
		if (s === 'failed') return 'badge-failed';
		if (s === 'running') return 'badge-running';
		return 'badge-queued';
	}

	function ago(ts: string) {
		const s = Math.round((Date.now() - new Date(ts).getTime()) / 1000);
		if (s < 60) return `${s}s`;
		if (s < 3600) return `${Math.round(s / 60)}m`;
		return `${Math.round(s / 3600)}h`;
	}

	function humanStage(stage: string): string {
		return stage ? stage.replace(/_/g, ' ') : 'queued';
	}

	function commandStageIndex(steps: CommandStep[], stage: string, status: string): number {
		if (!steps.length) return -1;
		if (status === 'succeeded' || status === 'completed') return steps.length - 1;
		const normalized = stage.toLowerCase();
		const exact = steps.findIndex((step) => step.key === normalized);
		if (exact >= 0) return exact;
		const fuzzy = steps.findIndex((step) => normalized.includes(step.key) || step.key.includes(normalized));
		return fuzzy >= 0 ? fuzzy : 0;
	}

	function commandProgressPct(steps: CommandStep[], index: number, status: string): number {
		if (!steps.length) return status === 'running' ? 35 : 0;
		if (status === 'succeeded' || status === 'completed') return 100;
		if (status === 'failed') return Math.max(5, Math.round((Math.max(index, 0) / steps.length) * 100));
		return Math.round(((Math.max(index, 0) + 0.35) / steps.length) * 100);
	}

	function commandLabel(commandType: string): string {
		return commandType.replace(/_/g, ' ');
	}

	function swatchBg(hue: number, status: string): string {
		const satN = status === 'not_downloaded' ? 15 : 42;
		const litN = status === 'not_downloaded' ? 72 : 52;
		const hi = `hsl(${hue},${Math.min(satN+18,92)}%,${Math.min(litN+24,93)}%)`;
		const base = `hsl(${hue},${satN}%,${litN}%)`;
		const shad = `hsl(${hue},${Math.max(satN-8,4)}%,${Math.max(litN-20,12)}%)`;
		return `radial-gradient(circle at 36% 30%, ${hi} 0%, ${base} 52%, ${shad} 100%)`;
	}

	function materialFallbackBg(group: DatasetGroup, mat: MatEntry): string {
		let hash = 0;
		for (let i = 0; i < mat.material_id.length; i += 1) {
			hash = ((hash << 5) - hash + mat.material_id.charCodeAt(i)) | 0;
		}
		const hue = (group.swatch_hue + Math.abs(hash % 84) - 42 + 360) % 360;
		return swatchBg(hue, mat.status);
	}

	$effect(() => {
		if (isVisible) {
			sceneRailSnippet.set(railContent);
			sceneBottomSnippet.set(bottomContent);
			return () => {
				sceneRailSnippet.set(null);
				sceneBottomSnippet.set(null);
			};
		} else {
			sceneRailSnippet.set(null);
			sceneBottomSnippet.set(null);
		}
	});
</script>

{#snippet activeCmdCard()}
	{#if activeCmd}
		{@const cmdType = String(activeCmd.command_type ?? '')}
		{@const steps = ISAAC_STAGES[cmdType] ?? []}
		{@const stage = String(activeCmd.progress_stage ?? '')}
		{@const message = String(activeCmd.progress_message ?? '')}
		{@const status = String(activeCmd.status ?? '')}
		{@const counts = (activeCmd.progress_counts as Record<string, number> | undefined) ?? {}}
		{@const hint = activeCmd.telemetry_hint as Record<string, unknown> | undefined}
		{@const details = activeCmd.progress_details as Record<string, unknown> | undefined}
		{@const stageElapsed = Number(details?.current_stage_elapsed_s ?? activeCmd.elapsed_s ?? 0)}
		{@const stepIndex = commandStageIndex(steps, stage || status, status)}
		{@const currentStep = steps[stepIndex]}
		{@const progressPct = commandProgressPct(steps, stepIndex, status)}
		{@const expectedNext = details?.expected_next_stage as Record<string, string> | undefined}
		{@const isRunning = status !== 'succeeded' && status !== 'completed' && status !== 'failed'}
		<div class="panel active-command-card">
			<div class="active-command-head">
				<div class="active-command-title">
					<span class="status-dot live status-amber active-command-dot"></span>
					<div>
						<div class="active-command-kicker">{L === 'kr' ? '실행 중' : 'Running'}</div>
						<div class="active-command-name">{commandLabel(cmdType)}</div>
					</div>
				</div>
				<div class="active-command-meta">
					<span class="badge badge-running">{status}</span>
					{#if steps.length}
						<span class="mono">{Math.min(stepIndex + 1, steps.length)}/{steps.length}</span>
					{/if}
					<span class="muted">{Math.round(stageElapsed)}s</span>
				</div>
			</div>

			<div class="active-command-progress" aria-label="Command progress">
				<div class="active-command-progress-bar" style:width={`${progressPct}%`}></div>
			</div>

			<div class="active-command-current" data-running={isRunning ? 'true' : 'false'}>
				{#if isRunning}
					<span class="step-spinner active-command-current-spinner" aria-hidden="true"></span>
				{/if}
				<span class="active-command-stage">
					{#if currentStep}
						{L === 'kr' ? currentStep.kr : currentStep.en}
					{:else}
						{humanStage(stage || status)}
					{/if}
				</span>
				{#if message}
					<span class="active-command-current-sub">{message}</span>
				{/if}
			</div>

			{#if steps.length}
				<div class="active-command-steps">
					{#each steps as step, i}
						{@const isDone = i < stepIndex || status === 'succeeded' || status === 'completed'}
						{@const isCurrent = i === stepIndex && status !== 'succeeded' && status !== 'completed'}
						<div class="active-command-step" data-state={isDone ? 'done' : isCurrent ? 'current' : 'todo'}>
							<span class="active-command-step-dot">
								{#if isCurrent}
									<span class="step-spinner active-command-step-spinner" aria-hidden="true"></span>
								{:else}
									{isDone ? '✓' : i + 1}
								{/if}
							</span>
							<span class="active-command-step-label">{L === 'kr' ? step.kr : step.en}</span>
						</div>
					{/each}
				</div>
			{/if}

			{#if stage}
				<details class="active-command-tech">
					<summary>{L === 'kr' ? '기술 로그' : 'Technical log'}</summary>
					<div class="active-command-tech-body">
						<span class="mono muted">{stage}</span>
						{#if message}<span class="muted">{message}</span>{/if}
					</div>
				</details>
			{/if}

			{#if expectedNext}
				<div class="active-command-next">
					<span class="muted">{L === 'kr' ? '다음:' : 'Next:'}</span>
					<span>{L === 'kr' ? expectedNext.kr : expectedNext.en}</span>
				</div>
			{/if}

			{#if Object.keys(counts).length > 0}
				<div class="active-command-counts">
					{#each Object.entries(counts) as [k, v]}
						<span><span class="mono">{k}</span>: {v}</span>
					{/each}
				</div>
			{/if}

			{#if hint}
				<div class="active-command-hint">
					{String(L === 'kr' ? hint.kr ?? hint.en ?? '' : hint.en ?? hint.kr ?? '')}
				</div>
			{/if}
		</div>
	{/if}
{/snippet}

{#snippet treeNode(node: ObjNode, depth: number)}
	{@const hasChildren = !!node.children?.length}
	{@const collapsed = !treeFilter && collapsedNodes.has(node.prim_path)}
	{@const visibleChildren = treeFilter
		? (node.children ?? []).filter(c => nodeMatchesFilter(c, treeFilter))
		: (node.children ?? [])}
	<div
		class="obj-tree-row {selectedPaths.has(node.prim_path) ? 'obj-tree-row-selected' : ''} {primarySelectedPath === node.prim_path ? 'obj-tree-row-primary' : ''}"
		role="treeitem"
		tabindex="0"
		aria-selected={selectedPaths.has(node.prim_path)}
		aria-expanded={hasChildren ? !collapsed : undefined}
		onclick={(e) => selectObj(node, e)}
		onkeydown={(e) => {
			if (e.key === 'Enter') selectObj(node, e);
			if (e.key === 'Escape') { e.preventDefault(); clearSelection(); }
			if (e.key === 'ArrowRight' && hasChildren && collapsed) toggleNode(node.prim_path);
			if (e.key === 'ArrowLeft' && hasChildren && !collapsed) toggleNode(node.prim_path);
		}}
		style="--tree-depth:{depth}"
	>
		<input
			type="checkbox"
			class="obj-tree-check"
			checked={selectedPaths.has(node.prim_path)}
			onclick={(e) => { e.stopPropagation(); toggleObjSelection(node); }}
			aria-label={selectedPaths.has(node.prim_path) ? 'Deselect' : 'Select'}
		/>
		{#if hasChildren}
			<button
				onclick={(e) => { e.stopPropagation(); toggleNode(node.prim_path); }}
				class="obj-tree-toggle"
				aria-label={collapsed ? 'Expand' : 'Collapse'}
			>{collapsed ? '▶' : '▼'}</button>
		{:else}
			<span class="obj-tree-toggle obj-tree-toggle-spacer"></span>
		{/if}
		<span class="obj-tree-kind">{node.kind === 'xform' ? 'dir' : node.kind === 'mesh' ? 'mesh' : 'obj'}</span>
		<span class="obj-tree-label mono" title={node.prim_path}>{node.name || node.prim_path.split('/').pop()}</span>
		{#if node.has_override}<span class="badge badge-running" style="font-size:0.55rem;padding:0 0.25rem">M</span>{/if}
		{#if node.visible === false}<span class="muted" style="font-size:0.65rem">H</span>{/if}
	</div>
	{#if hasChildren && (!collapsed || treeFilter)}
		{#each visibleChildren as child}
			{@render treeNode(child, depth + 1)}
		{/each}
	{/if}
{/snippet}

{#snippet incidentsCard()}
	<Card padding="sm" elevation="none">
		{#snippet header()}
			<span class="card-eyebrow">{L === 'kr' ? '인시던트' : 'Incidents'}</span>
			<h3 class="card-title">{L === 'kr' ? '주의 필요' : 'Needs attention'}</h3>
		{/snippet}
		<button class="incident-summary-chip" type="button" onclick={jumpToJobsTab}
			title={L === 'kr' ? '하단 작업 큐로 이동' : 'Jump to work queue'}>
			<span>{L === 'kr' ? '실행 중' : 'Running'} <strong>{runningCount}</strong></span>
			<span class="dot">·</span>
			<span>{L === 'kr' ? '대기' : 'Queued'} <strong>{queuedJobsCount}</strong></span>
			<span class="dot">·</span>
			<span class="fail">{L === 'kr' ? '실패' : 'Failed'} <strong>{failedJobsCount}</strong></span>
		</button>
		<div class="incident-filter-row" role="tablist" aria-label={L === 'kr' ? '인시던트 필터' : 'Incident filter'}>
			{#each [['all', L === 'kr' ? '전체' : 'All'], ['danger', L === 'kr' ? '실패' : 'Fail'], ['warning', L === 'kr' ? '주의' : 'Warn']] as [k, lbl]}
				<button
					type="button"
					class="filter-chip incident-filter-btn"
					class:active={incidentFilter === k}
					onclick={() => incidentFilter = k as typeof incidentFilter}
				>{lbl}</button>
			{/each}
		</div>
		{#if visibleIncidents.length === 0}
			<div class="empty-state text-xs">{L === 'kr' ? '활성 인시던트 없음' : 'No active incidents'}</div>
		{:else}
			<div class="rail-stack-inner">
				{#each visibleIncidents as inc (inc.key)}
					<IncidentCard
						collapsible
						expanded={expandedIncidentId === inc.key}
						onToggle={() => expandedIncidentId = expandedIncidentId === inc.key ? null : inc.key}
						tone={inc.tone}
						title={inc.title}
						description={inc.description}
						source={inc.source}
						timestamp={inc.timestamp}
					>
						{#snippet actions()}
							<button
								class="button button-primary text-xs"
								onclick={(e) => { e.stopPropagation(); handleRetry(inc.jobId); }}
								disabled={retryingJobId === inc.jobId}
							>{retryingJobId === inc.jobId ? '…' : (L === 'kr' ? '재시도' : 'Retry')}</button>
							{#if expandedIncidentId === inc.key}
								<a class="button button-subtle text-xs" href="/jobs/{inc.jobId}" onclick={(e) => e.stopPropagation()}>{L === 'kr' ? '로그' : 'Logs'}</a>
								<a class="button button-subtle text-xs" href="/jobs/{inc.jobId}" onclick={(e) => e.stopPropagation()}>{L === 'kr' ? '상세' : 'Detail'}</a>
							{/if}
						{/snippet}
						{#snippet expandedContent()}
							{#if inc.fullError}
								<pre class="inc-trace">{inc.fullError}</pre>
							{/if}
							{#if inc.relatedJobs && inc.relatedJobs.length > 0}
								<div class="inc-related">
									<span class="muted text-xs">{L === 'kr' ? '관련 잡' : 'Related jobs'}:</span>
									{#each inc.relatedJobs as rid}
										<a class="mono text-xs" href="/jobs/{rid}" onclick={(e) => e.stopPropagation()}>{rid.slice(0, 12)}</a>
									{/each}
								</div>
							{/if}
						{/snippet}
					</IncidentCard>
				{/each}
			</div>
		{/if}
	</Card>
{/snippet}

{#snippet pipelineCard()}
	<Card padding="sm" elevation="none">
		{#snippet header()}
			<span class="card-eyebrow">{L === 'kr' ? '연동 상태' : 'Bridge Status'}</span>
			<h3 class="card-title">Bridge Pipeline</h3>
		{/snippet}
		<ul class="pipeline-list">
			{#each pipelineSteps as step (step.key)}
				<li class="pipeline-row" data-state={step.state}>
					<span class="pipeline-dot pipeline-dot-{pipelineDot(step.state)}">{pipelineGlyph(step.state)}</span>
					<span class="pipeline-label">{L === 'kr' ? step.label_kr : step.label_en}</span>
					{#if step.hint}
						<span class="muted text-xs pipeline-hint">{step.hint}</span>
					{:else}
						<span></span>
					{/if}
					<span class="pipeline-state text-xs muted">{step.state}</span>
				</li>
			{/each}
		</ul>
	</Card>
{/snippet}

{#snippet sceneInfoCard()}
	<Card padding="sm" elevation="none">
		{#snippet header()}
			<span class="card-eyebrow">{L === 'kr' ? '장면 정보' : 'Scene Info'}</span>
			<h3 class="card-title">{currentSceneId ?? '—'}</h3>
		{/snippet}
		<KeyValueList items={sceneInfoKv} size="sm" dense />
	</Card>
{/snippet}

{#snippet materialBrowserPanel()}
	<InlineMaterialPicker
		sceneId={currentSceneId}
		targetPrimPaths={selectedTargetPaths}
		onApplied={() => { void refresh({ force: true }); }}
	/>
{/snippet}

{#snippet selectionDetailPanel()}
	{#if selectedObj}
		<div style="display:flex;flex-direction:column;gap:0.5rem">
			{#if selectedCount > 1}
				<div style="display:flex;align-items:center;gap:0.5rem;padding:0.25rem 0.4rem;background:rgba(99,102,241,0.08);border-radius:4px;font-size:0.75rem">
					<strong>{selectedCount}{L === 'kr' ? '개 선택됨' : ' selected'}</strong>
					<span class="muted">· {L === 'kr' ? '대표' : 'primary'}: <span class="mono">{selectedObj.prim_path}</span></span>
					<button type="button" class="button button-ghost text-xs" style="margin-left:auto" onclick={clearSelection}>
						{L === 'kr' ? '선택 해제' : 'Clear'}
					</button>
				</div>
				<details>
					<summary class="text-xs muted" style="cursor:pointer">{L === 'kr' ? '선택된 prim 목록' : 'Selected prims'}</summary>
					<div style="max-height:160px;overflow-y:auto;display:flex;flex-direction:column;gap:2px;padding-top:4px">
						{#each [...selectedPaths] as p}
							<span class="mono text-xs" style="padding:1px 4px;background:rgba(99,102,241,0.04);border-radius:2px">{p}</span>
						{/each}
					</div>
				</details>
			{/if}
			<Breadcrumb items={breadcrumbItems} separator="/" ariaLabel={L === 'kr' ? '선택 경로' : 'Selection path'} />
			<KeyValueList items={selectionKv} layout="columns" size="sm" />
		</div>
	{:else}
		<div class="empty-state text-xs">{L === 'kr' ? '오브젝트가 선택되지 않았습니다' : 'No object selected'}</div>
	{/if}
{/snippet}

{#snippet isaacHistoryCard(cmd: Record<string, unknown>)}
	{@const cmdType = String(cmd.command_type ?? '')}
	{@const status = String(cmd.status ?? '')}
	{@const normalized = status === 'completed' ? 'succeeded' : status === 'dispatched' ? 'running' : status}
	{@const stage = String(cmd.progress_stage ?? '')}
	{@const message = String(cmd.progress_message ?? '')}
	{@const createdAt = typeof cmd.created_at === 'string' ? Date.parse(cmd.created_at) : NaN}
	{@const finishedAt = typeof cmd.completed_at === 'string'
		? Date.parse(cmd.completed_at)
		: typeof cmd.updated_at === 'string' ? Date.parse(cmd.updated_at) : NaN}
	{@const elapsedS = Number.isFinite(createdAt) && Number.isFinite(finishedAt)
		? Math.max(0, Math.round((finishedAt - createdAt) / 1000)) : null}
	{@const isError = normalized === 'failed'}
	<div class="panel active-command-card" data-history-state={normalized}>
		<div class="active-command-head">
			<div class="active-command-title">
				<span class="status-dot {isError ? 'status-red' : 'status-green'}"></span>
				<div>
					<div class="active-command-kicker">{L === 'kr' ? '완료된 명령' : 'Completed command'}</div>
					<div class="active-command-name">{commandTypeLabel(cmdType, L as 'kr' | 'en')}</div>
				</div>
			</div>
			<div class="active-command-meta">
				<span class="badge {statusClass(normalized)}">{normalized}</span>
				{#if elapsedS !== null}<span class="muted">{elapsedS}s</span>{/if}
			</div>
		</div>

		{#if message}
			<div class="active-command-current" data-running="false">
				<span class="cmd-toast-icon" aria-hidden="true" style:background={isError ? 'rgb(220,38,38)' : 'rgb(22,163,74)'}>{isError ? '✕' : '✓'}</span>
				<span class="active-command-stage">
					{isError ? (L === 'kr' ? '실패' : 'Failed') : (L === 'kr' ? '성공' : 'Succeeded')}
				</span>
				<span class="active-command-current-sub">{message}</span>
			</div>
		{/if}

		{#if stage}
			<details class="active-command-tech">
				<summary>{L === 'kr' ? '기술 로그' : 'Technical log'}</summary>
				<div class="active-command-tech-body">
					<span class="mono muted">{stage}</span>
					{#if String(cmd.command_id ?? '')}<span class="mono muted">id: {String(cmd.command_id)}</span>{/if}
					{#if typeof cmd.created_at === 'string'}<span class="muted">{L === 'kr' ? '시작' : 'Started'}: {cmd.created_at}</span>{/if}
					{#if typeof cmd.completed_at === 'string'}<span class="muted">{L === 'kr' ? '완료' : 'Completed'}: {cmd.completed_at}</span>{/if}
				</div>
			</details>
		{/if}
	</div>
{/snippet}

{#snippet renderJobDetailCard(job: Record<string, unknown>)}
	{@const jobId = String(job.job_id ?? '')}
	{@const status = String(job.status ?? '')}
	{@const stage = String(job.progress_stage ?? '')}
	{@const curIdx = stageIndex(stage)}
	{@const pct = status === 'succeeded' ? 100
		: status === 'failed' ? Math.max(5, Math.round((Math.max(curIdx, 0) / STAGES.length) * 100))
		: Math.round(((Math.max(curIdx, 0) + 0.35) / STAGES.length) * 100)}
	{@const error = job.error ? String(job.error) : ''}
	<div class="panel active-command-card">
		<div class="active-command-head">
			<div class="active-command-title">
				<span class="status-dot live" class:status-amber={status === 'running'}
					class:status-red={status === 'failed'}
					class:status-green={status === 'succeeded'}></span>
				<div>
					<div class="active-command-kicker">{L === 'kr' ? '렌더 잡' : 'Render job'}</div>
					<div class="active-command-name mono">{jobId.slice(0, 24)}</div>
				</div>
			</div>
			<div class="active-command-meta">
				<span class="badge {statusClass(status)}">{status}</span>
				<span class="mono">{Math.min(Math.max(curIdx, 0) + 1, STAGES.length)}/{STAGES.length}</span>
				{#if job.finished_at}<span class="muted">{ago(String(job.finished_at))} ago</span>{/if}
			</div>
		</div>
		<div class="active-command-progress"><div class="active-command-progress-bar" style:width={`${pct}%`}></div></div>
		<div class="active-command-current" data-running={status === 'running' ? 'true' : 'false'}>
			{#if status === 'running'}<span class="step-spinner active-command-current-spinner" aria-hidden="true"></span>{/if}
			<span class="active-command-stage">{humanStage(stage)}</span>
			{#if job.scene_id}<span class="active-command-current-sub mono">{String(job.scene_id)}</span>{/if}
		</div>
		<div class="active-command-steps">
			{#each STAGES as st, i}
				{@const isDone = i < curIdx || status === 'succeeded'}
				{@const isCurrent = i === curIdx && status === 'running'}
				<div class="active-command-step" data-state={isDone ? 'done' : isCurrent ? 'current' : 'todo'}>
					<span class="active-command-step-dot">
						{#if isCurrent}<span class="step-spinner active-command-step-spinner" aria-hidden="true"></span>
						{:else}{isDone ? '✓' : i + 1}{/if}
					</span>
					<span class="active-command-step-label">{L === 'kr' ? st.kr : st.en}</span>
				</div>
			{/each}
		</div>
		{#if error}
			<pre class="inc-trace" style="margin-top:0.5rem">{error}</pre>
		{/if}
		<div class="job-detail-actions">
			{#if status === 'failed'}
				<button class="button button-primary text-xs" onclick={() => handleRetry(jobId)}
					disabled={retryingJobId === jobId}>
					{retryingJobId === jobId ? '…' : (L === 'kr' ? '재시도' : 'Retry')}
				</button>
			{/if}
			<a class="button button-subtle text-xs" href="/jobs">{L === 'kr' ? '로그' : 'Logs'}</a>
			<button class="button button-subtle text-xs" onclick={() => handleDeleteJob(jobId, status)}
				disabled={deletingJobId === jobId}>
				{deletingJobId === jobId ? '…' : (L === 'kr' ? '삭제' : 'Delete')}
			</button>
		</div>
	</div>
{/snippet}

{#snippet jobsTabPanel()}
	<div class="job-hub">
		<aside class="job-hub-list">
			{#if jobListGroups.length === 0}
				<div class="empty-state text-xs">{L === 'kr' ? '작업 없음' : 'No jobs'}</div>
			{:else}
				{#each jobListGroups as group (group.labelKey)}
					<div class="job-hub-group">
						<div class="job-hub-group-label">
							<span>{group.label}</span>
							<span class="muted">{group.rows.length}</span>
						</div>
						{#each group.rows as row (row.key)}
							<div
								class="job-hub-row"
								class:active={selectedJobKey === row.key}
								role="button"
								tabindex="0"
								aria-pressed={selectedJobKey === row.key}
								onclick={() => selectedJobKey = row.key}
								onkeydown={(e) => {
									if (e.key === 'Enter' || e.key === ' ') {
										e.preventDefault();
										selectedJobKey = row.key;
									}
								}}
							>
								<span class="badge {statusClass(row.status)}">{row.status}</span>
								<span class="job-hub-row-title mono">{row.title}</span>
								{#if row.stage}
									<span class="muted text-xs job-hub-row-stage">{row.stage.replace(/_/g, ' ')}</span>
								{/if}
								{#if row.status === 'failed' && row.kind === 'render'}
									<button
										type="button"
										class="button button-primary text-xs job-hub-row-retry"
										onclick={(e) => { e.stopPropagation(); handleRetry(row.key); }}
										disabled={retryingJobId === row.key}
									>{retryingJobId === row.key ? '…' : (L === 'kr' ? '재시도' : 'Retry')}</button>
								{/if}
							</div>
						{/each}
					</div>
				{/each}
			{/if}
		</aside>
		<section class="job-hub-detail">
			{#if !selectedJobKey}
				<div class="empty-state text-xs">{L === 'kr' ? '왼쪽에서 작업을 선택하세요' : 'Select a job from the list'}</div>
			{:else if selectedJobKey.startsWith('isaac:') || selectedJobKey === ISAAC_JOB_KEY}
				{@const cid = selectedJobKey.startsWith('isaac:') ? selectedJobKey.slice('isaac:'.length) : String(activeCmd?.command_id ?? '')}
				{@const isActiveSelection = !!activeCmd && cid === String(activeCmd.command_id ?? '')}
				{#if isActiveSelection}
					{@render activeCmdCard()}
				{:else}
					{@const cmd = recentIsaacCommands.find(c => String(c.command_id ?? '') === cid)}
					{#if cmd}
						{@render isaacHistoryCard(cmd)}
					{:else}
						<div class="empty-state text-xs">{L === 'kr' ? '명령 기록을 찾을 수 없음' : 'Command not found'}</div>
					{/if}
				{/if}
			{:else}
				{@const job = recentJobs.find(j => String(j.job_id) === selectedJobKey)}
				{#if job}
					{@render renderJobDetailCard(job)}
				{:else}
					<div class="empty-state text-xs">{L === 'kr' ? '작업 정보를 찾을 수 없음' : 'Job not found'}</div>
				{/if}
			{/if}
		</section>
	</div>
{/snippet}

{#snippet historyTabPanel()}
	{#if jobRows.length === 0}
		<div class="empty-state text-xs">{L === 'kr' ? '이력 없음' : 'No history yet'}</div>
	{:else}
		<DataTable
			columns={jobColumns}
			rows={jobRows}
			rowKey={(r) => r.job_id}
			onRowClick={(r) => goto(`/jobs/${r.job_id}`)}
		/>
	{/if}
{/snippet}

{#snippet logsTabPanel()}
	<LogList
		entries={recentLogs}
		emptyMessage={L === 'kr' ? '최근 로그 없음' : 'No recent activity'}
		dense
	/>
{/snippet}

{#snippet railContent()}
	<div style="display:flex;flex-direction:column;gap:0.75rem;padding:0.75rem;height:100%;overflow-y:auto">
		{@render incidentsCard()}
		{@render pipelineCard()}
		{@render sceneInfoCard()}
	</div>
{/snippet}

{#snippet bottomContent()}
	<div class="bottom-tabs-shell" data-collapsed={$bottomPanelCollapsed} data-orientation="vertical">
		<div class="bottom-tabs-rail bottom-tabs-rail-vertical" role="tablist" aria-label={L === 'kr' ? '하단 탭' : 'Bottom tabs'}>
			<button
				class="bottom-collapse-btn"
				type="button"
				onclick={toggleBottomPanel}
				aria-expanded={!$bottomPanelCollapsed}
				aria-label={$bottomPanelCollapsed ? (L === 'kr' ? '하단 영역 펼치기' : 'Expand bottom area') : (L === 'kr' ? '하단 영역 접기' : 'Collapse bottom area')}
				title={$bottomPanelCollapsed ? (L === 'kr' ? '펼치기' : 'Expand') : (L === 'kr' ? '접기' : 'Collapse')}
			>{$bottomPanelCollapsed ? '▶' : '◀'}</button>
			{#each bottomTabs as tab}
				<button
					type="button"
					class="bottom-tab-btn {bottomTab === tab.id ? 'active' : ''}"
					role="tab"
					aria-selected={bottomTab === tab.id}
					disabled={tab.disabled}
					onclick={() => {
						bottomTab = tab.id as BottomTabId;
						if ($bottomPanelCollapsed) toggleBottomPanel();
					}}
					title={tab.label}
				>
					<span class="bottom-tab-label">{tab.label}</span>
					{#if tab.badge != null}
						<span class="bottom-tab-badge">{tab.badge}</span>
					{/if}
				</button>
			{/each}
		</div>
		{#if !$bottomPanelCollapsed}
			<div class="bottom-tabs-body">
				{#if bottomTab === 'jobs'}
					{@render jobsTabPanel()}
				{:else if bottomTab === 'logs'}
					{@render logsTabPanel()}
				{:else if bottomTab === 'selection'}
					{@render selectionDetailPanel()}
				{:else if bottomTab === 'history'}
					{@render historyTabPanel()}
				{:else if bottomTab === 'materials'}
					{@render materialBrowserPanel()}
				{/if}
			</div>
		{/if}
	</div>
{/snippet}

<div class="cs-root">

{#if cmdMsg}<div class="text-xs muted cs-cmd-msg">{cmdMsg}</div>{/if}

{#if loading}
	<div class="muted text-sm" style="flex:1;display:flex;align-items:center;justify-content:center">{L === 'kr' ? '로딩 중…' : 'Loading…'}</div>

{:else if !currentSceneId}
	<!-- 씬 없음 -->
	<div class="panel">
		<div class="panel-label">{L === 'kr' ? '현재 씬 없음' : 'No Current Scene'}</div>
		<p class="muted text-sm mt-2">{L === 'kr' ? '등록된 씬에서 연결하거나 Isaac Sim에서 씬을 열어주세요.' : 'Connect from a registered scene or open a scene in Isaac Sim.'}</p>
		{#if registeredScenes.length > 0}
			<div class="table-wrap mt-3">
				<table class="table">
					<thead><tr><th>Scene ID</th><th>Ready</th><th></th></tr></thead>
					<tbody>
						{#each registeredScenes as sc}
							{@const s = sc as Record<string, unknown>}
							<tr>
								<td class="mono text-xs">{s.scene_id}</td>
								<td>{#if s.render_ready}<span class="badge badge-succeeded">ready</span>{:else}<span class="badge badge-queued">—</span>{/if}</td>
								<td>
									<div class="flex gap-2">
										<button class="button button-primary text-xs" onclick={() => sendCommand('connect_session', String(s.scene_id))} disabled={!!cmdPending}>Connect</button>
										<button class="button button-subtle text-xs" onclick={() => sendCommand('load_scene', String(s.scene_id))} disabled={!!cmdPending}>Load</button>
										<a href="/scenes/{s.scene_id}" class="button button-subtle text-xs">→</a>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>

{:else}
	<!-- ── 2-col main grid: [tree+selection] + [viewport] ── -->
	<div class="cs-grid">
		<!-- ══ LEFT column: Scene Tree (top) + Selection card (bottom) ══ -->
		<div class="cs-left-col">
			<div class="panel cs-tree-panel">
				<div class="cs-tree-head">
					<span class="panel-label">{L === 'kr' ? '오브젝트 트리' : 'Scene Tree'}</span>
					{#if objectInventory.length}<span class="tab-badge">{treeCount}</span>{/if}
					{#if objectInventory.length}
						<button class="obj-tree-mini-btn" type="button" onclick={collapseTree} title={L === 'kr' ? '트리 접기' : 'Collapse tree'}>−</button>
						<button class="obj-tree-mini-btn" type="button" onclick={expandAllTree} title={L === 'kr' ? '트리 펼치기' : 'Expand tree'}>+</button>
					{/if}
					<input
						bind:value={treeFilter}
						placeholder={L === 'kr' ? '검색…' : 'Filter…'}
						class="obj-tree-filter"
					/>
				</div>
				{#if !sessionConnected}
					<div class="empty-state mt-2 text-xs">{L === 'kr' ? 'Isaac 연결 후 트리 표시' : 'Connect Isaac to see tree'}</div>
				{:else if objectInventory.length === 0}
					<div class="empty-state mt-2 text-xs">{L === 'kr' ? '오브젝트 없음' : 'No objects'}</div>
				{:else}
					<div class="obj-tree-scroll" role="tree" aria-label={L === 'kr' ? '오브젝트 트리' : 'Object tree'}>
						{#each filteredTree as node}
							{@render treeNode(node, 0)}
						{/each}
					</div>
				{/if}
			</div>

			{#if selectedObj}
				<!-- Floating overlay anchored to the bottom of .cs-left-col.
				     Only mounts when something is selected so the tree
				     gets the full vertical height when nothing is picked. -->
				<div class="panel cs-selection-panel">
					<div class="cs-selection-head">
						<span class="card-eyebrow">{L === 'kr' ? '선택' : 'Selection'}</span>
						<span class="badge badge-running">{selectedObj.kind ?? 'object'}</span>
						<button
							type="button"
							class="cs-selection-close"
							onclick={clearSelection}
							aria-label={L === 'kr' ? '선택 해제' : 'Clear selection'}
							title={L === 'kr' ? '선택 해제' : 'Clear selection'}
						>×</button>
					</div>
					{@render selectionDetailPanel()}
				</div>
			{/if}
		</div>

		<!-- ══ RIGHT: Viewport with toolbar + materials drawer overlay ══ -->
		<div class="panel cs-viewport-panel">
			<div class="cs-viewport-toolbar">
				<div class="vt-group vt-group-left">
					<div class="vt-chip-group" role="group" aria-label={L === 'kr' ? '레이어 필터' : 'Layer filters'}>
						<button class="vt-chip {layerFilters.has('scene') ? 'active' : ''}" onclick={() => toggleLayer('scene')}>{L === 'kr' ? '장면' : 'Scene'}</button>
						<button class="vt-chip {layerFilters.has('render') ? 'active' : ''}" onclick={() => toggleLayer('render')}>{L === 'kr' ? '렌더' : 'Render'}</button>
						<button class="vt-chip {layerFilters.has('shape') ? 'active' : ''}" onclick={() => toggleLayer('shape')}>{L === 'kr' ? 'Shape' : 'Shape Map'}</button>
					</div>
				</div>
				<div class="vt-group vt-group-mid">
					<div class="vt-mode" role="group" aria-label={L === 'kr' ? '맵 패널' : 'Map panels'}>
						<button
							class="vt-mode-btn {viewMode === '2d' ? 'active' : ''}"
							onclick={() => { viewMode = '2d'; }}
						>
							2D Map
						</button>
						<button
							class="vt-mode-btn {viewMode === '3d' ? 'active' : ''}"
							onclick={() => { viewMode = '3d'; }}
						>
							3D Blueprint
						</button>
						<button
							class="vt-mode-btn {viewMode === 'nav' ? 'active' : ''}"
							onclick={() => { viewMode = 'nav'; }}
							title={L === 'kr' ? '주행용 2D occupancy map' : '2D navigation/occupancy map'}
						>
							🧭 Navigation
						</button>
					</div>
					{#if floorplanImgSrc && viewMode === '2d'}
						<div class="vt-zoom">
							<button class="button button-ghost text-xs" onclick={() => zoomBy(1/1.2)} aria-label="Zoom out">−</button>
							<span class="mono muted text-xs vt-zoom-pct">{Math.round(mapZoom*100)}%</span>
							<button class="button button-ghost text-xs" onclick={() => zoomBy(1.2)} aria-label="Zoom in">+</button>
							<button class="button button-ghost text-xs" onclick={resetMapView} title="Reset">⤢</button>
						</div>
					{/if}
				</div>
				<div class="vt-group vt-group-right">
					{#if currentSceneId && viewMode === '3d'}
						<button
							class="button button-subtle text-xs"
							onclick={handlePrepareBasic}
							disabled={!!prepareBasicDisabledReason}
							title={prepareBasicDisabledReason
								? (L === 'kr' ? `비활성 이유: ${prepareBasicDisabledReason}` : `Disabled: ${prepareBasicDisabledReason}`)
								: (L === 'kr' ? 'Isaac 없이 Mitsuba XML에서 기본 스냅샷/shape_map 재생성' : 'Rebuild basic snapshot/shape_map from Mitsuba XML (Isaac-free)')}
						>
							{preparingBasicNow ? (L === 'kr' ? '생성 중…' : 'Building…') : (L === 'kr' ? '기본 스냅샷' : 'Basic snapshot')}
						</button>
						<Tooltip title={bp3dPrepareTip.title} text={bp3dPrepareTip.text} position="bottom">
							<button
								class="button button-subtle text-xs"
								onclick={() => sendCommand('prepare_render_ready')}
								disabled={!!cmdPending || preparingNow || !sessionConnected}
							>
								{preparingNow ? (L === 'kr' ? '장면 준비 중…' : 'Preparing scene…') : (L === 'kr' ? '장면 준비' : 'Prepare Scene')}
							</button>
						</Tooltip>
					{/if}
					<button class="button button-ghost text-xs" onclick={handleSmokeRender} disabled={!!cmdPending} title="Smoke Render">🧪</button>
				</div>
			</div>

			<div class="cs-viewport-stage">
				{#if viewMode === '2d'}
					<div class="viewport-pane viewport-pane-2d">
						{#if floorplanImgSrc}
							<!-- svelte-ignore a11y_no_static_element_interactions -->
							<div
								bind:this={mapViewport}
								class="viewport-canvas-wrap"
								style:cursor={isPanning ? 'grabbing' : 'grab'}
								onwheel={onMapWheel}
								onpointerdown={onMapPointerDown}
								onpointermove={onMapPointerMove}
								onpointerup={onMapPointerUp}
								onpointercancel={onMapPointerUp}
								ondragstart={(e) => e.preventDefault()}
							>
								<div class="viewport-canvas-center">
									<div class="viewport-canvas-transform" style:transform={`translate(${mapPanX}px,${mapPanY}px) scale(${mapZoom})`} style:transition={isPanning ? 'none' : 'transform 0.1s ease'}>
								<img
											bind:this={mapImg}
											src={floorplanImgSrc}
											alt="Floorplan"
											class="viewport-img viewport-img-mirrored"
											draggable="false"
											onload={onMapLoad}
											onerror={onFloorplanImageError}
										/>
										<canvas
											bind:this={mapCanvas}
											class="viewport-canvas"
										></canvas>
									</div>
								</div>
							</div>
							<div class="viewport-legend">
								<span><span class="viewport-legend-dot" style="background:rgb(47,123,246)"></span>{L === 'kr' ? '활성 카메라' : 'Active cam'}</span>
								<span><span class="viewport-legend-dot" style="background:rgb(230,126,34)"></span>{L === 'kr' ? '요청 카메라' : 'Req. cam'}</span>
								<span><span class="viewport-legend-dot" style="background:rgb(22,163,74)"></span>{L === 'kr' ? '씬 카메라' : 'Scene cam'}</span>
								<span><span class="viewport-legend-dot" style="background:rgb(245,158,11)"></span>{L === 'kr' ? '로봇' : 'Robot'}</span>
								{#if selectedObj}<span><span class="viewport-legend-dot" style="border:2px solid #dc2626;background:transparent"></span>{L === 'kr' ? '선택' : 'Selected'}</span>{/if}
								<a href="/api/scenes/{currentSceneId}/floorplan" class="button button-subtle text-xs viewport-legend-json" target="_blank">JSON</a>
							</div>
						{:else if currentSceneId}
							<div class="viewport-empty">
								<div class="muted text-sm">
									{floorplanError
										? (L === 'kr' ? '2D 맵을 불러오지 못했습니다' : 'Failed to load 2D map')
										: (L === 'kr' ? '도면 생성 중…' : 'Generating floorplan…')}
								</div>
								<div class="muted text-xs mt-1">
									{floorplanError
										? floorplanError
										: (L === 'kr' ? '씬이 로드되면 자동 생성됩니다' : 'Auto-generated when scene is loaded')}
								</div>
							</div>
						{/if}
					</div>
				{:else if viewMode === '3d'}
					<div class="viewport-pane viewport-pane-3d">
						<CurrentSceneBlueprint3D
							sceneId={currentSceneId}
							selectedPath={selectedObj?.prim_path ?? null}
							selectedPaths={selectedTargetPaths}
							activeCamera={liveActiveViewportCamera}
						/>
					</div>
				{:else}
					<div class="viewport-pane viewport-pane-nav">
						<CurrentSceneNavigationMap
							sceneId={currentSceneId}
							selectedAabbs={null}
						/>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

</div>

<style>
	.cs-root {
		height: 100%;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-height: 0;
	}

	.cs-cmd-msg {
		margin: 0;
		padding: 0.25rem 0.5rem;
		background: var(--brand-soft, rgba(47, 123, 246, 0.06));
		color: var(--brand-strong);
		border-radius: var(--radius-sm);
		font-weight: 600;
		flex-shrink: 0;
	}

	/* ── Main 2-col grid ── */
	.cs-grid {
		display: grid;
		grid-template-columns: minmax(280px, 320px) minmax(0, 1fr);
		gap: var(--space-3);
		flex: 1;
		min-height: 0;
		overflow: hidden;
		align-items: stretch;
	}
	/* Left column: tree fills the full height, selection card floats at the
	   bottom as an overlay so multi-select doesn't squeeze the tree. The
	   relative positioning anchors the absolute selection card. */
	.cs-left-col {
		position: relative;
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
	}
	.cs-tree-panel {
		flex: 1 1 auto;
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
	}
	.cs-tree-head {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		flex-shrink: 0;
	}
	.cs-selection-panel {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		z-index: 5;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		max-height: 45%;
		overflow: auto;
		/* Float over the tree with a soft shadow + slightly translucent
		   surface so the underlying tree remains hinted at. */
		background: var(--panel, #fff);
		border: 1px solid var(--panel-border, rgba(0, 0, 0, 0.08));
		border-radius: var(--radius-lg, 10px);
		box-shadow: 0 -6px 18px rgba(15, 23, 42, 0.12);
		padding: 0.5rem 0.6rem;
		backdrop-filter: blur(6px);
	}
	.cs-selection-head {
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}
	.cs-selection-close {
		margin-left: auto;
		width: 1.4rem;
		height: 1.4rem;
		border: none;
		background: transparent;
		font-size: 1.05rem;
		line-height: 1;
		cursor: pointer;
		color: var(--muted, #6b7280);
		border-radius: 4px;
	}
	.cs-selection-close:hover {
		background: rgba(0, 0, 0, 0.06);
		color: var(--text, #1f2330);
	}

	/* ── Viewport panel + toolbar ── */
	.cs-viewport-panel {
		padding: var(--space-2);
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow: hidden;
		position: relative;
	}
	.cs-viewport-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
		padding: 0 0.25rem 0.5rem;
		flex-shrink: 0;
		flex-wrap: wrap;
	}
	.vt-group {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
	}
	.vt-group-mid { flex: 1 1 auto; justify-content: center; }
	.vt-group-right { margin-left: auto; }
	.vt-chip-group {
		display: inline-flex;
		gap: 2px;
		background: var(--surface-2);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		padding: 2px;
	}
	.vt-chip {
		background: transparent;
		border: none;
		padding: 0.2rem 0.55rem;
		font-size: var(--font-size-xs);
		font-weight: 500;
		color: var(--muted);
		cursor: pointer;
		border-radius: calc(var(--radius-sm) - 1px);
	}
	.vt-chip:hover { color: var(--text); }
	.vt-chip.active {
		background: var(--panel);
		color: var(--text);
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
	}
	.vt-mode {
		display: inline-flex;
		gap: 2px;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		padding: 2px;
		background: var(--surface-2);
	}
	.vt-mode-btn {
		display: inline-flex;
		align-items: center;
		border: none;
		padding: 0.2rem 0.6rem;
		font-size: var(--font-size-xs);
		font-weight: 600;
		color: var(--muted);
		border-radius: calc(var(--radius-sm) - 1px);
		background: transparent;
		cursor: pointer;
	}
	.vt-mode-btn.active {
		color: var(--text);
		background: rgba(37, 99, 235, 0.12);
		box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.08);
	}
	.vt-spacer { flex: 1; }
	.vt-zoom {
		display: inline-flex;
		align-items: center;
		gap: 0.2rem;
	}
	.vt-zoom-pct {
		min-width: 2.5rem;
		text-align: center;
	}

	.cs-viewport-stage {
		position: relative;
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}
	.viewport-pane {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		padding: 0.3rem;
		border: 1px solid rgba(148, 163, 184, 0.22);
		border-radius: calc(var(--radius-lg) - 4px);
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.96));
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
	}
	.viewport-pane-2d {
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.92));
	}
	.viewport-pane-3d {
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(244, 247, 250, 0.96));
	}
	.viewport-canvas-wrap {
		position: relative;
		background: #0a0a0a;
		border-radius: var(--radius-sm);
		overflow: hidden;
		flex: 1;
		min-height: 18rem;
		touch-action: none;
		user-select: none;
		-webkit-user-drag: none;
	}
	.viewport-canvas-center {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		pointer-events: none;
	}
	.viewport-canvas-transform {
		position: relative;
		transform-origin: center center;
	}
	.viewport-img {
		display: block;
		max-width: 100%;
		max-height: 100%;
		user-select: none;
		pointer-events: none;
	}
	.viewport-img-mirrored {
		transform: scaleX(-1);
		transform-origin: center center;
	}
	.viewport-canvas {
		position: absolute;
		top: 0;
		left: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
	}
	.viewport-legend {
		display: flex;
		gap: 0.75rem;
		margin-top: 0.4rem;
		padding: 0 0.15rem;
		font-size: 0.68rem;
		color: var(--muted);
		flex-shrink: 0;
		flex-wrap: wrap;
		align-items: center;
	}
	.viewport-legend-dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		margin-right: 3px;
	}
	.viewport-legend-json { margin-left: auto; }
	.viewport-empty {
		flex: 1;
		min-height: 18rem;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.25rem;
	}

	.material-panel-split {
		display: grid;
		grid-template-columns: 11rem minmax(0, 1fr);
		gap: var(--space-3);
		height: 100%;
		min-height: 0;
	}
	.material-tool-rail {
		display: flex;
		flex-direction: column;
		gap: 0.55rem;
		min-height: 0;
		overflow: hidden;
		border-right: 1px solid var(--panel-border);
		padding-right: var(--space-3);
	}
	.material-target-chip {
		font-size: 0.68rem;
		background: rgba(37, 99, 235, 0.08);
		border-radius: 0.35rem;
		padding: 0.35rem 0.5rem;
		color: var(--brand-strong);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.material-search {
		width: 100%;
		font-size: 0.8rem;
	}
	.material-filter-stack {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}
	.material-filter-btn {
		width: 100%;
		justify-content: flex-start;
		font-size: 0.72rem;
		padding: 0.28rem 0.5rem;
	}
	.material-content-section {
		margin-bottom: 0.8rem;
	}
	.material-section-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.4rem;
	}
	.material-preset-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
	}
	.material-preset-btn {
		appearance: none;
		border: 1px solid var(--panel-border);
		background: var(--panel);
		color: var(--text);
		border-radius: var(--radius-sm);
		padding: 0.35rem 0.5rem;
		font: inherit;
		font-size: 0.72rem;
		text-align: left;
		cursor: pointer;
	}
	.material-preset-btn:hover,
	.material-preset-btn:focus-visible {
		border-color: rgba(47, 123, 246, 0.32);
		background: var(--brand-soft);
	}
	.material-scroll-area {
		min-height: 0;
		overflow-y: auto;
		padding-right: 0.25rem;
	}
	.category-chip-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem;
		margin-bottom: 0.6rem;
		position: sticky;
		top: 0;
		z-index: 1;
		padding-bottom: 0.35rem;
		background: var(--panel);
	}
	.category-chip {
		appearance: none;
		border: 1px solid var(--panel-border);
		background: transparent;
		color: var(--text-muted, var(--text));
		border-radius: 999px;
		padding: 0.2rem 0.65rem;
		font: inherit;
		font-size: 0.7rem;
		cursor: pointer;
		transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
	}
	.category-chip:hover,
	.category-chip:focus-visible {
		border-color: rgba(47, 123, 246, 0.4);
		color: var(--text);
		outline: none;
	}
	.category-chip.active {
		background: var(--brand-soft);
		border-color: rgba(47, 123, 246, 0.55);
		color: var(--brand-strong, var(--text));
		font-weight: 600;
	}
	.material-swatch-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
	}
	.material-swatch-tile {
		appearance: none;
		position: relative;
		width: 3.2rem;
		height: 3.2rem;
		border: 1px solid transparent;
		border-radius: 0.45rem;
		background: transparent;
		padding: 0;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		overflow: visible;
	}
	.material-swatch-tile:hover,
	.material-swatch-tile:focus-visible {
		border-color: rgba(47, 123, 246, 0.34);
		background: var(--brand-soft);
		outline: none;
	}
	.material-swatch-sphere {
		position: relative;
		width: 2.25rem;
		height: 2.25rem;
		border-radius: 999px;
		overflow: hidden;
		border: 1px solid rgba(148, 163, 184, 0.22);
		box-shadow:
			inset -0.45rem -0.45rem 0.8rem rgba(15, 23, 42, 0.18),
			inset 0.45rem 0.45rem 0.7rem rgba(255, 255, 255, 0.78),
			0 0.25rem 0.65rem rgba(15, 23, 42, 0.12);
	}
	.material-swatch-img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		border-radius: 999px;
		object-fit: cover;
		display: none;
	}
	/* ── Bottom panel tabs (vertical rail) ── */
	.bottom-tabs-shell {
		display: grid;
		grid-template-columns: 108px minmax(0, 1fr);
		height: 100%;
		min-height: 0;
	}
	.bottom-tabs-shell[data-collapsed='true'] {
		grid-template-columns: 108px;
	}
	.bottom-tabs-rail {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		padding: 0.5rem 0.4rem;
		border-right: 1px solid var(--panel-border);
		background: var(--panel-soft, var(--subpanel));
		min-height: 0;
		overflow-y: auto;
	}
	.bottom-collapse-btn,
	.bottom-tab-btn {
		appearance: none;
		border: 0;
		background: transparent;
		color: var(--muted-strong);
		border-radius: var(--radius-sm);
		min-height: 1.85rem;
		padding: 0.4rem 0.55rem;
		font: inherit;
		font-size: 0.74rem;
		font-weight: 600;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: flex-start;
		gap: 0.4rem;
		text-align: left;
		position: relative;
	}
	.bottom-collapse-btn {
		justify-content: center;
		color: var(--brand-strong);
		background: rgba(47, 123, 246, 0.08);
		margin-bottom: 0.25rem;
	}
	.bottom-tab-btn:hover:not(:disabled) {
		background: rgba(47, 123, 246, 0.06);
	}
	.bottom-tab-btn.active {
		color: var(--brand-strong);
		background: rgba(47, 123, 246, 0.06);
		font-weight: var(--font-weight-semibold, 650);
	}
	.bottom-tab-btn.active::before {
		content: '';
		position: absolute;
		left: -0.4rem;
		top: 6px;
		bottom: 6px;
		width: 3px;
		border-radius: 0 2px 2px 0;
		background: var(--brand);
	}
	.bottom-tab-btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.bottom-tab-label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		flex: 1;
	}
	.bottom-tab-badge {
		margin-left: auto;
		min-width: 1.1rem;
		height: 1.1rem;
		border-radius: var(--radius-pill);
		background: var(--brand-soft);
		color: var(--brand-strong);
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 0 0.35rem;
		font-size: var(--font-size-2xs);
		font-weight: 600;
	}
	.bottom-tabs-body {
		min-height: 0;
		overflow: auto;
		padding: 0.75rem;
	}

	/* ── Right rail stack + pipeline list ── */
	.rail-stack-inner {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.pipeline-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.pipeline-row {
		display: grid;
		grid-template-columns: 1.25rem 1fr auto;
		grid-template-areas: 'dot label state' 'dot hint hint';
		align-items: center;
		gap: 0 0.5rem;
		padding: 0.3rem 0.4rem;
		border-radius: var(--radius-sm);
		font-size: var(--font-size-xs);
	}
	.pipeline-row[data-state='running'] { background: rgba(245, 158, 11, 0.08); }
	.pipeline-row[data-state='failed']  { background: rgba(220, 38, 38, 0.06); }
	.pipeline-dot {
		grid-area: dot;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.1rem;
		height: 1.1rem;
		border-radius: 50%;
		font-size: 0.7rem;
		font-weight: bold;
		color: white;
	}
	.pipeline-dot-success { background: #16a34a; }
	.pipeline-dot-active  { background: #f59e0b; }
	.pipeline-dot-danger  { background: #dc2626; }
	.pipeline-dot-neutral { background: var(--muted); color: var(--panel); }
	.pipeline-label { grid-area: label; color: var(--text); font-weight: 500; }
	.pipeline-hint  { grid-area: hint; }
	.pipeline-state { grid-area: state; text-transform: lowercase; }

	/* ── Card eyebrow/title fallbacks (in case not in app.css) ── */
	.card-eyebrow {
		font-size: 0.62rem;
		text-transform: uppercase;
		letter-spacing: var(--letter-spacing-wide);
		color: var(--muted);
		font-weight: 700;
	}
	.card-title {
		font-size: var(--font-size-sm);
		font-weight: 600;
		color: var(--text);
		margin: 0;
	}

	/* ── Responsive: collapse to single col below 1280px ── */
	@media (max-width: 1280px) {
		.cs-grid {
			grid-template-columns: minmax(0, 1fr);
			grid-auto-rows: auto;
		}
		.cs-left-col {
			grid-template-rows: minmax(220px, 38vh) auto;
		}
		.cs-selection-panel { max-height: none; }
		.material-panel-split { grid-template-columns: 1fr; }
		.material-tool-rail {
			border-right: none;
			border-bottom: 1px solid var(--panel-border);
			padding-right: 0;
			padding-bottom: var(--space-3);
			overflow: visible;
		}
		.material-filter-stack {
			flex-direction: row;
			flex-wrap: wrap;
		}
		.material-filter-btn,
		.material-preset-btn {
			width: auto;
		}
		.viewport-pane-3d {
			min-height: 22rem;
		}
	}
</style>

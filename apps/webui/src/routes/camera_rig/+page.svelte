<script lang="ts">
	import { onMount } from 'svelte';
	import CameraRigEditor3D from '$lib/CameraRigEditor3D.svelte';
	import {
		applyCameraRigToIsaac,
		getCameraRig,
		getCameraRigRobotMesh,
		listCameraRigs,
		saveCameraRig,
		type CameraRig,
		type CameraRigMeshPayload,
		type CameraRigRenderSettings,
		type CameraRigSensor,
		type CameraRigSensorType
	} from '$lib/api';

	type ViewMode = '3d' | 'top' | 'front' | 'side';
	type ViewportHandle = { setView?: (mode: ViewMode) => void };

	const sensorTypes: CameraRigSensorType[] = ['rgb_camera', 'nir_camera', 'polar_camera', 'lidar_3d'];
	const modalitiesByType: Record<CameraRigSensorType, string[]> = {
		rgb_camera: ['rgb'],
		nir_camera: ['nir_intensity'],
		polar_camera: ['polar_rgb_preview', 'dop', 'aolp', 's1', 's2'],
		lidar_3d: ['lidar_point_cloud']
	};
	const renderSettingKeys = ['path_spp', 'aov_spp', 'polar_spp', 'samples_per_pass'] as const;
	type RenderSettingKey = typeof renderSettingKeys[number];

	let viewport: ViewportHandle | null = null;
	let rig: CameraRig | null = null;
	let meshPayload: CameraRigMeshPayload | null = null;
	let selectedSensorId = '';
	let viewMode: ViewMode = '3d';
	let status = 'Loading camera rig preset';
	let error = '';
	let saving = false;
	let applying = false;
	let robotPrimPath = '/World/RangerMini';

	let selectedSensor: CameraRigSensor | null = null;
	let rigStats = summarizeRig(null);
	$: selectedSensor = rig?.sensors.find((sensor) => sensor.sensor_id === selectedSensorId) ?? rig?.sensors[0] ?? null;
	$: rigStats = summarizeRig(rig);

	onMount(async () => {
		try {
			const rigs = await listCameraRigs();
			const defaultRigId = rigs.default_rig_id || 'ranger_mini_default';
			const [loadedRig, mesh] = await Promise.all([getCameraRig(defaultRigId), getCameraRigRobotMesh()]);
			rig = loadedRig;
			meshPayload = mesh;
			selectedSensorId = loadedRig.sensors[0]?.sensor_id ?? '';
			status = mesh.status === 'ready' ? 'Ranger Mini mesh loaded' : 'Ranger Mini proxy loaded';
		} catch (exc) {
			error = exc instanceof Error ? exc.message : String(exc);
			status = 'Failed to load rig';
		}
	});

	function cloneRig(source: CameraRig): CameraRig {
		return JSON.parse(JSON.stringify(source)) as CameraRig;
	}

	function patchSensor(sensorId: string, updater: (sensor: CameraRigSensor) => void) {
		if (!rig) return;
		const next = cloneRig(rig);
		const sensor = next.sensors.find((item) => item.sensor_id === sensorId);
		if (!sensor) return;
		updater(sensor);
		rig = next;
	}

	function setView(mode: ViewMode) {
		viewMode = mode;
		viewport?.setView?.(mode);
	}

	function selectSensor(sensorId: string) {
		selectedSensorId = sensorId;
	}

	function moveSensor(sensorId: string, xyz: [number, number, number]) {
		patchSensor(sensorId, (sensor) => {
			sensor.mount.xyz_m = xyz;
		});
	}

	function uniqueSensorId(base: string) {
		if (!rig) return base;
		const existing = new Set(rig.sensors.map((sensor) => sensor.sensor_id));
		if (!existing.has(base)) return base;
		for (let idx = 2; idx < 999; idx += 1) {
			const candidate = `${base}_${idx}`;
			if (!existing.has(candidate)) return candidate;
		}
		return `${base}_${Date.now()}`;
	}

	function defaultRenderSettingsFor(type: CameraRigSensorType): CameraRigRenderSettings {
		if (type === 'lidar_3d') {
			return { path_spp: 1, aov_spp: 1, polar_spp: 1, samples_per_pass: null };
		}
		return { path_spp: 4096, aov_spp: 16, polar_spp: 256, samples_per_pass: null };
	}

	function renderSettingValue(sensor: CameraRigSensor, key: RenderSettingKey): number | '' {
		const fallback = defaultRenderSettingsFor(sensor.sensor_type);
		const value = sensor.render?.[key] ?? fallback[key];
		return value === null || value === undefined ? '' : Number(value);
	}

	function makeSensor(type: CameraRigSensorType): CameraRigSensor {
		const sensorId = uniqueSensorId(type === 'lidar_3d' ? 'lidar_top' : `${type.replace('_camera', '')}_cam`);
		const sensor: CameraRigSensor = {
			sensor_id: sensorId,
			sensor_type: type,
			modalities: [...modalitiesByType[type]],
			enabled: true,
			mount: {
				parent_frame: rig?.base_frame ?? 'base_link',
				xyz_m: [0, 0.35, 0.75],
				rpy_deg: [0, 0, 0]
			},
			intrinsics: {
				resolution: [640, 360],
				fov_h_deg: 75,
				fov_v_deg: 60,
				focal_length_px: 410,
				clip_near_m: 0.1,
				clip_far_m: 30
			},
			render: defaultRenderSettingsFor(type)
		};
		if (type === 'nir_camera') {
			sensor.nir = { wavelength_min_nm: 830, wavelength_max_nm: 870, active_emitter_radiance: 40 };
		}
		if (type === 'polar_camera') {
			sensor.polarization = { polarizer_angle_deg: 0 };
		}
		if (type === 'lidar_3d') {
			sensor.lidar = {
				horizontal_samples: 1024,
				vertical_channels: 32,
				horizontal_fov_deg: 360,
				vertical_fov_min_deg: -25,
				vertical_fov_max_deg: 15,
				min_range_m: 0.2,
				max_range_m: 80,
				wavelength_nm: 905
			};
		}
		return sensor;
	}

	function addSensor(type: CameraRigSensorType = 'rgb_camera') {
		if (!rig) return;
		const next = cloneRig(rig);
		const sensor = makeSensor(type);
		next.sensors = [...next.sensors, sensor];
		rig = next;
		selectedSensorId = sensor.sensor_id;
	}

	function duplicateSensor() {
		if (!rig || !selectedSensor) return;
		const next = cloneRig(rig);
		const clone = JSON.parse(JSON.stringify(selectedSensor)) as CameraRigSensor;
		clone.sensor_id = uniqueSensorId(`${selectedSensor.sensor_id}_copy`);
		clone.mount.xyz_m = [
			clone.mount.xyz_m[0] + 0.08,
			clone.mount.xyz_m[1],
			clone.mount.xyz_m[2]
		];
		next.sensors = [...next.sensors, clone];
		rig = next;
		selectedSensorId = clone.sensor_id;
	}

	function deleteSensor() {
		if (!rig || !selectedSensor) return;
		const next = cloneRig(rig);
		next.sensors = next.sensors.filter((sensor) => sensor.sensor_id !== selectedSensor.sensor_id);
		rig = next;
		selectedSensorId = next.sensors[0]?.sensor_id ?? '';
	}

	function changeSensorType(type: CameraRigSensorType) {
		if (!selectedSensor) return;
		patchSensor(selectedSensor.sensor_id, (sensor) => {
			sensor.sensor_type = type;
			sensor.modalities = [...modalitiesByType[type]];
			sensor.render ??= defaultRenderSettingsFor(type);
			if (type === 'nir_camera') sensor.nir ??= { wavelength_min_nm: 830, wavelength_max_nm: 870, active_emitter_radiance: 40 };
			else delete sensor.nir;
			if (type === 'polar_camera') sensor.polarization ??= { polarizer_angle_deg: 0 };
			else delete sensor.polarization;
			if (type === 'lidar_3d') {
				sensor.lidar ??= {
					horizontal_samples: 1024,
					vertical_channels: 32,
					horizontal_fov_deg: 360,
					vertical_fov_min_deg: -25,
					vertical_fov_max_deg: 15,
					min_range_m: 0.2,
					max_range_m: 80,
					wavelength_nm: 905
				};
			} else delete sensor.lidar;
		});
	}

	function renameSelectedSensor(value: string) {
		if (!selectedSensor) return;
		const previous = selectedSensor.sensor_id;
		const nextId = value.trim() || previous;
		patchSensor(previous, (sensor) => {
			sensor.sensor_id = nextId;
		});
		selectedSensorId = nextId;
	}

	function updateNumber(path: 'position' | 'rotation' | 'resolution' | 'intrinsics', indexOrKey: number | keyof CameraRigSensor['intrinsics'], value: string) {
		if (!selectedSensor) return;
		const number = Number(value);
		if (!Number.isFinite(number)) return;
		patchSensor(selectedSensor.sensor_id, (sensor) => {
			if (path === 'position' && typeof indexOrKey === 'number') sensor.mount.xyz_m[indexOrKey] = number;
			if (path === 'rotation' && typeof indexOrKey === 'number') sensor.mount.rpy_deg[indexOrKey] = number;
			if (path === 'resolution' && typeof indexOrKey === 'number') sensor.intrinsics.resolution[indexOrKey] = Math.max(1, Math.round(number));
			if (path === 'intrinsics' && typeof indexOrKey === 'string') sensor.intrinsics[indexOrKey] = number as never;
		});
	}

	function updateRenderNumber(key: RenderSettingKey, value: string) {
		if (!selectedSensor) return;
		if (key === 'samples_per_pass' && value.trim() === '') {
			patchSensor(selectedSensor.sensor_id, (sensor) => {
				sensor.render ??= defaultRenderSettingsFor(sensor.sensor_type);
				sensor.render.samples_per_pass = null;
			});
			return;
		}
		const number = Number(value);
		if (!Number.isFinite(number)) return;
		patchSensor(selectedSensor.sensor_id, (sensor) => {
			sensor.render ??= defaultRenderSettingsFor(sensor.sensor_type);
			sensor.render[key] = Math.max(1, Math.round(number)) as never;
		});
	}

	async function saveRig() {
		if (!rig) return;
		saving = true;
		error = '';
		try {
			rig = await saveCameraRig(rig.rig_id, rig);
			status = `Saved ${rig.rig_id}`;
		} catch (exc) {
			error = exc instanceof Error ? exc.message : String(exc);
		} finally {
			saving = false;
		}
	}

	async function applyRig() {
		if (!rig) return;
		applying = true;
		error = '';
		try {
			await saveRig();
			await applyCameraRigToIsaac(rig.rig_id, {
				robot_prim_path: robotPrimPath.trim() || undefined,
				replace_existing: true
			});
			status = `Queued Apply to Isaac for ${rig.rig_id}`;
		} catch (exc) {
			error = exc instanceof Error ? exc.message : String(exc);
		} finally {
			applying = false;
		}
	}

	function summarizeRig(source: CameraRig | null) {
		const sensors = source?.sensors ?? [];
		const active = sensors.filter((sensor) => sensor.enabled);
		const maxHeight = sensors.reduce((acc, sensor) => Math.max(acc, sensor.mount.xyz_m[2]), 0);
		const width = sensors.length ? Math.max(...sensors.map((sensor) => sensor.mount.xyz_m[0])) - Math.min(...sensors.map((sensor) => sensor.mount.xyz_m[0])) : 0;
		const depth = sensors.length ? Math.max(...sensors.map((sensor) => sensor.mount.xyz_m[1])) - Math.min(...sensors.map((sensor) => sensor.mount.xyz_m[1])) : 0;
		return { total: sensors.length, active: active.length, maxHeight, width, depth };
	}
</script>

<svelte:head>
	<title>Camera Rig Editor · RoboMitsuba</title>
</svelte:head>

<main class="camera-rig-page">
	<section class="toolbar">
		<div>
			<h1>Camera Rig Editor</h1>
			<p>Ranger Mini mounted sensor layout and physical metadata preset</p>
		</div>
		<div class="toolbar-actions">
			<div class="view-switch" aria-label="View mode">
				{#each (['3d', 'top', 'front', 'side'] as ViewMode[]) as mode}
					<button class:active={viewMode === mode} on:click={() => setView(mode)}>
						{mode === '3d' ? '3D' : mode[0].toUpperCase() + mode.slice(1)}
					</button>
				{/each}
			</div>
			<button class="primary" disabled={!rig || saving} on:click={saveRig}>{saving ? 'Saving' : 'Save JSON'}</button>
			<button class="primary strong" disabled={!rig || applying} on:click={applyRig}>{applying ? 'Applying' : 'Apply to Isaac'}</button>
		</div>
	</section>

	{#if error}
		<section class="notice error">{error}</section>
	{:else}
		<section class="notice">{status}</section>
	{/if}

	<section class="editor-shell">
		<div class="left-pane">
			<div class="viewport-panel">
				<CameraRigEditor3D
					bind:this={viewport}
					{rig}
					{meshPayload}
					{selectedSensorId}
					on:select={(event) => selectSensor(event.detail.sensor_id)}
					on:move={(event) => moveSensor(event.detail.sensor_id, event.detail.xyz_m)}
				/>
				<div class="viewport-hud">
					<span>Left drag sensor: move</span>
					<span>Empty drag: orbit</span>
					<span>Scroll: zoom</span>
				</div>
			</div>

			<div class="sensor-list">
				<div class="table-title">
					<h2>Sensors in Rig ({rigStats.total})</h2>
					<div>
						<button on:click={() => addSensor('rgb_camera')}>Add RGB</button>
						<button on:click={() => addSensor('nir_camera')}>Add NIR</button>
						<button on:click={() => addSensor('polar_camera')}>Add Polar</button>
						<button on:click={() => addSensor('lidar_3d')}>Add LiDAR</button>
					</div>
				</div>
				<table>
					<thead>
						<tr>
							<th>Sensor</th>
							<th>Type</th>
							<th>Resolution</th>
							<th>FOV</th>
							<th>Position</th>
							<th>Status</th>
						</tr>
					</thead>
					<tbody>
						{#each rig?.sensors ?? [] as sensor}
							<tr class:selected={sensor.sensor_id === selectedSensorId} on:click={() => selectSensor(sensor.sensor_id)}>
								<td>{sensor.sensor_id}</td>
								<td><span class="pill">{sensor.sensor_type.replace('_camera', '').replace('lidar_3d', 'lidar')}</span></td>
								<td>{sensor.intrinsics.resolution[0]} x {sensor.intrinsics.resolution[1]}</td>
								<td>{sensor.intrinsics.fov_h_deg} x {sensor.intrinsics.fov_v_deg}</td>
								<td>({sensor.mount.xyz_m.map((v) => v.toFixed(2)).join(', ')})</td>
								<td><span class:active-dot={sensor.enabled} class="status-dot"></span>{sensor.enabled ? 'Active' : 'Off'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>

		<aside class="right-pane">
			{#if selectedSensor}
				<section class="panel selected-panel">
					<div class="panel-head">
						<div>
							<label for="selected-sensor-id">Selected Sensor</label>
							<input
								id="selected-sensor-id"
								class="name-input"
								value={selectedSensor.sensor_id}
								on:change={(event) => renameSelectedSensor((event.currentTarget as HTMLInputElement).value)}
							/>
						</div>
						<label class="toggle">
							<input
								type="checkbox"
								checked={selectedSensor.enabled}
								on:change={(event) => patchSensor(selectedSensor.sensor_id, (sensor) => (sensor.enabled = (event.currentTarget as HTMLInputElement).checked))}
							/>
							Active
						</label>
					</div>

					<div class="form-grid">
						<label>
							Type
							<select value={selectedSensor.sensor_type} on:change={(event) => changeSensorType((event.currentTarget as HTMLSelectElement).value as CameraRigSensorType)}>
								{#each sensorTypes as type}
									<option value={type}>{type}</option>
								{/each}
							</select>
						</label>
						<label>
							Parent Frame
							<input
								value={selectedSensor.mount.parent_frame}
								on:input={(event) => patchSensor(selectedSensor.sensor_id, (sensor) => (sensor.mount.parent_frame = (event.currentTarget as HTMLInputElement).value))}
							/>
						</label>
					</div>

					<h3>Extrinsics</h3>
					<div class="triple-grid">
						{#each ['X', 'Y', 'Z'] as axis, index}
							<label>{axis} m<input type="number" step="0.01" value={selectedSensor.mount.xyz_m[index]} on:input={(event) => updateNumber('position', index, (event.currentTarget as HTMLInputElement).value)} /></label>
						{/each}
					</div>
					<div class="triple-grid">
						{#each ['Roll', 'Pitch', 'Yaw'] as axis, index}
							<label>{axis} deg<input type="number" step="1" value={selectedSensor.mount.rpy_deg[index]} on:input={(event) => updateNumber('rotation', index, (event.currentTarget as HTMLInputElement).value)} /></label>
						{/each}
					</div>
					<div class="quick-orient">
						<button on:click={() => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.mount.rpy_deg = [0, 0, 0]))}>Front</button>
						<button on:click={() => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.mount.rpy_deg = [0, 0, 90]))}>Left</button>
						<button on:click={() => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.mount.rpy_deg = [0, 0, -90]))}>Right</button>
						<button on:click={() => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.mount.rpy_deg = [0, 0, 180]))}>Rear</button>
					</div>

					<h3>Intrinsics</h3>
					<div class="form-grid">
						<label>Width<input type="number" min="1" value={selectedSensor.intrinsics.resolution[0]} on:input={(event) => updateNumber('resolution', 0, (event.currentTarget as HTMLInputElement).value)} /></label>
						<label>Height<input type="number" min="1" value={selectedSensor.intrinsics.resolution[1]} on:input={(event) => updateNumber('resolution', 1, (event.currentTarget as HTMLInputElement).value)} /></label>
						<label>FOV H<input type="number" step="1" value={selectedSensor.intrinsics.fov_h_deg} on:input={(event) => updateNumber('intrinsics', 'fov_h_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
						<label>FOV V<input type="number" step="1" value={selectedSensor.intrinsics.fov_v_deg} on:input={(event) => updateNumber('intrinsics', 'fov_v_deg', (event.currentTarget as HTMLInputElement).value)} /></label>
						<label>Near<input type="number" step="0.01" value={selectedSensor.intrinsics.clip_near_m} on:input={(event) => updateNumber('intrinsics', 'clip_near_m', (event.currentTarget as HTMLInputElement).value)} /></label>
						<label>Far<input type="number" step="1" value={selectedSensor.intrinsics.clip_far_m} on:input={(event) => updateNumber('intrinsics', 'clip_far_m', (event.currentTarget as HTMLInputElement).value)} /></label>
					</div>

					{#if selectedSensor.sensor_type === 'nir_camera' && selectedSensor.nir}
						<h3>NIR</h3>
						<div class="form-grid">
							<label>Min nm<input type="number" value={selectedSensor.nir.wavelength_min_nm} on:input={(event) => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.nir!.wavelength_min_nm = Number((event.currentTarget as HTMLInputElement).value)))} /></label>
							<label>Max nm<input type="number" value={selectedSensor.nir.wavelength_max_nm} on:input={(event) => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.nir!.wavelength_max_nm = Number((event.currentTarget as HTMLInputElement).value)))} /></label>
							<label>Emitter<input type="number" value={selectedSensor.nir.active_emitter_radiance} on:input={(event) => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.nir!.active_emitter_radiance = Number((event.currentTarget as HTMLInputElement).value)))} /></label>
						</div>
					{/if}
					{#if selectedSensor.sensor_type === 'polar_camera' && selectedSensor.polarization}
						<h3>Polarization</h3>
						<label>Polarizer angle deg<input type="number" value={selectedSensor.polarization.polarizer_angle_deg} on:input={(event) => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.polarization!.polarizer_angle_deg = Number((event.currentTarget as HTMLInputElement).value)))} /></label>
					{/if}
					{#if selectedSensor.sensor_type === 'lidar_3d' && selectedSensor.lidar}
						<h3>LiDAR</h3>
						<div class="form-grid">
							<label>Samples<input type="number" value={selectedSensor.lidar.horizontal_samples} on:input={(event) => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.lidar!.horizontal_samples = Math.round(Number((event.currentTarget as HTMLInputElement).value))))} /></label>
							<label>Channels<input type="number" value={selectedSensor.lidar.vertical_channels} on:input={(event) => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.lidar!.vertical_channels = Math.round(Number((event.currentTarget as HTMLInputElement).value))))} /></label>
							<label>Range min<input type="number" value={selectedSensor.lidar.min_range_m} on:input={(event) => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.lidar!.min_range_m = Number((event.currentTarget as HTMLInputElement).value)))} /></label>
							<label>Range max<input type="number" value={selectedSensor.lidar.max_range_m} on:input={(event) => patchSensor(selectedSensor!.sensor_id, (sensor) => (sensor.lidar!.max_range_m = Number((event.currentTarget as HTMLInputElement).value)))} /></label>
						</div>
					{/if}

					<h3>Render Quality</h3>
					<div class="form-grid">
						<label>Path SPP<input type="number" min="1" step="1" value={renderSettingValue(selectedSensor, 'path_spp')} on:input={(event) => updateRenderNumber('path_spp', (event.currentTarget as HTMLInputElement).value)} /></label>
						<label>AOV SPP<input type="number" min="1" step="1" value={renderSettingValue(selectedSensor, 'aov_spp')} on:input={(event) => updateRenderNumber('aov_spp', (event.currentTarget as HTMLInputElement).value)} /></label>
						<label>Polar/NIR SPP<input type="number" min="1" step="1" value={renderSettingValue(selectedSensor, 'polar_spp')} on:input={(event) => updateRenderNumber('polar_spp', (event.currentTarget as HTMLInputElement).value)} /></label>
						<label>Samples / pass<input type="number" min="1" step="1" placeholder="auto" value={renderSettingValue(selectedSensor, 'samples_per_pass')} on:input={(event) => updateRenderNumber('samples_per_pass', (event.currentTarget as HTMLInputElement).value)} /></label>
					</div>

					<div class="danger-row">
						<button class="outline" on:click={duplicateSensor}>Duplicate</button>
						<button class="danger" on:click={deleteSensor}>Remove</button>
					</div>
				</section>
			{/if}

			<section class="panel">
				<h2>Rig Overview</h2>
				<dl>
					<div><dt>Total Sensors</dt><dd>{rigStats.total}</dd></div>
					<div><dt>Active Sensors</dt><dd>{rigStats.active}</dd></div>
					<div><dt>Max Height</dt><dd>{rigStats.maxHeight.toFixed(2)} m</dd></div>
					<div><dt>Rig Width</dt><dd>{rigStats.width.toFixed(2)} m</dd></div>
					<div><dt>Rig Depth</dt><dd>{rigStats.depth.toFixed(2)} m</dd></div>
				</dl>
				<label>
					Isaac Robot Prim
					<input value={robotPrimPath} on:input={(event) => (robotPrimPath = (event.currentTarget as HTMLInputElement).value)} />
				</label>
			</section>
		</aside>
	</section>
</main>

<style>
	.camera-rig-page {
		display: flex;
		flex-direction: column;
		gap: 14px;
		padding: 18px;
		color: #0f172a;
	}

	.toolbar,
	.notice,
	.editor-shell,
	.panel,
	.sensor-list {
		border: 1px solid #dbe4ef;
		background: #ffffff;
		border-radius: 8px;
	}

	.toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 16px;
	}

	h1,
	h2,
	h3,
	p {
		margin: 0;
	}

	h1 {
		font-size: 22px;
	}

	h2 {
		font-size: 15px;
	}

	h3 {
		margin-top: 16px;
		font-size: 13px;
	}

	p,
	label,
	dt,
	td,
	th,
	.notice {
		font-size: 12px;
	}

	.toolbar-actions,
	.view-switch,
	.table-title,
	.danger-row,
	.quick-orient {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	button,
	input,
	select {
		border: 1px solid #d5deeb;
		border-radius: 6px;
		background: #ffffff;
		color: #0f172a;
		font: inherit;
		min-height: 34px;
	}

	button {
		padding: 0 12px;
		cursor: pointer;
	}

	button.active,
	button.primary {
		border-color: #2563eb;
		color: #1d4ed8;
		background: #eff6ff;
	}

	button.strong {
		background: #2563eb;
		color: #ffffff;
	}

	button.danger {
		border-color: #fecaca;
		color: #dc2626;
	}

	button.outline {
		border-color: #93c5fd;
		color: #2563eb;
	}

	button:disabled {
		opacity: 0.55;
		cursor: default;
	}

	input,
	select {
		width: 100%;
		padding: 0 10px;
	}

	.notice {
		padding: 10px 12px;
		color: #334155;
	}

	.notice.error {
		color: #b91c1c;
		background: #fef2f2;
	}

	.editor-shell {
		display: grid;
		grid-template-columns: minmax(0, 1.4fr) minmax(340px, 0.7fr);
		gap: 14px;
		padding: 14px;
		min-height: 720px;
	}

	.left-pane,
	.right-pane {
		display: flex;
		flex-direction: column;
		gap: 14px;
		min-width: 0;
	}

	.viewport-panel {
		position: relative;
		min-height: 510px;
		overflow: hidden;
		border: 1px solid #dbe4ef;
		border-radius: 8px;
		background: #f8fafc;
	}

	.viewport-hud {
		position: absolute;
		left: 12px;
		bottom: 12px;
		display: flex;
		gap: 10px;
		padding: 8px 10px;
		border-radius: 6px;
		background: rgba(255, 255, 255, 0.88);
		box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
		font-size: 12px;
		color: #475569;
	}

	.sensor-list,
	.panel {
		padding: 14px;
	}

	.table-title {
		justify-content: space-between;
		margin-bottom: 10px;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		table-layout: fixed;
	}

	th,
	td {
		padding: 10px 8px;
		border-bottom: 1px solid #e5edf6;
		text-align: left;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	tr.selected {
		background: #eff6ff;
		outline: 1px solid #93c5fd;
	}

	.pill {
		display: inline-flex;
		padding: 3px 7px;
		border-radius: 999px;
		background: #eef2ff;
		color: #3730a3;
		font-size: 11px;
	}

	.status-dot {
		display: inline-block;
		width: 7px;
		height: 7px;
		margin-right: 6px;
		border-radius: 50%;
		background: #94a3b8;
	}

	.status-dot.active-dot {
		background: #22c55e;
	}

	.panel-head {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 14px;
	}

	.panel-head label {
		display: flex;
		flex-direction: column;
		gap: 6px;
		color: #64748b;
	}

	.name-input {
		font-size: 18px;
		font-weight: 700;
		border-color: transparent;
		padding-left: 0;
	}

	.toggle {
		display: flex;
		align-items: center;
		flex-direction: row;
		gap: 8px;
	}

	.toggle input {
		width: auto;
	}

	.form-grid,
	.triple-grid {
		display: grid;
		gap: 10px;
		margin-top: 10px;
	}

	.form-grid {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}

	.triple-grid {
		grid-template-columns: repeat(3, minmax(0, 1fr));
	}

	label {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-weight: 600;
		color: #334155;
	}

	.quick-orient {
		margin-top: 10px;
		flex-wrap: wrap;
	}

	.danger-row {
		justify-content: stretch;
		margin-top: 18px;
	}

	.danger-row button {
		flex: 1;
	}

	dl {
		display: grid;
		gap: 8px;
		margin: 12px 0 16px;
	}

	dl div {
		display: flex;
		justify-content: space-between;
		gap: 12px;
	}

	dd {
		margin: 0;
		font-weight: 700;
	}

	@media (max-width: 1180px) {
		.editor-shell {
			grid-template-columns: 1fr;
		}

		.viewport-panel {
			min-height: 420px;
		}
	}
</style>

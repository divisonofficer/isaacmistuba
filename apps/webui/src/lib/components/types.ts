export type Tone = 'success' | 'warning' | 'danger' | 'active' | 'info' | 'neutral';
export type Size = 'sm' | 'md' | 'lg';
export type Variant = 'solid' | 'soft' | 'outline' | 'ghost';

export interface BreadcrumbItem {
	label: string;
	href?: string;
}

export interface TabItem {
	id: string;
	label: string;
	badge?: string | number;
	disabled?: boolean;
}

export interface DataTableColumn<Row = Record<string, unknown>> {
	key: keyof Row & string;
	label: string;
	align?: 'left' | 'center' | 'right';
	width?: string;
	mono?: boolean;
}

export interface LogEntry {
	ts: string | Date;
	level: 'info' | 'warn' | 'error' | 'debug';
	message: string;
	source?: string;
}

export interface KeyValueItem {
	key: string;
	value: string | number;
	mono?: boolean;
	tone?: Tone;
}

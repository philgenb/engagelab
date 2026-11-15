export type Stream = {
  uid: string;
  name: string;
  type: string;
  source_id: string;
  channel_count: number;
  nominal_srate: number;
  sample_count?: number;
  status?: string;
  last_sample_local?: number | null;
  video_format?: "mp4";
  video_file?: string;
  video_timing_file?: string;
  video_status?: "recording" | "ready" | "empty" | "failed";
  video_frame_count?: number;
  video_first_frame_session_seconds?: number;
  video_error?: string;
  video_warning?: string;
};
export type Session = {
  id: string;
  name: string;
  game: string;
  status: string;
  created_at: string;
  started_at?: string;
  ended_at?: string;
  duration_seconds?: number;
  error?: string;
  streams: Stream[];
};


// Studios table (configuration)
interface Studio {
  id: string;           // slug: "dev", "design", "content"
  api_key_hash: string; // for authentication
  wave: number;         // 1 or 2
  created_at: timestamp;
}

// Missions table (registry)
interface Mission {
  id: string;           // UUID v4
  studio_id: string;    // FK to studios
  type: 'saas_conversion' | 'infrastructure' | 'meta';
  status: 'active' | 'completed' | 'blocked' | 'at_risk';
  target_completion: timestamp;
  metadata: jsonb;      // flexible mission context
  created_at: timestamp;
  updated_at: timestamp;
}

// Progress Events table (high volume, partitioned by month)
interface ProgressEvent {
  id: string;           // UUID v4
  mission_id: string;   // FK to missions
  studio_id: string;    // denormalized for query perf
  checkpoint: string;     // "api_design", "auth_impl", "testing"
  percent_complete: number; // 0-100
  status: 'on_track' | 'delayed' | 'blocked';
  blockers: string[];   // array of blocker descriptions
  metrics: jsonb;       // flexible: { lines_of_code: 1500, tests_passing: 45 }
  recorded_at: timestamp; // event time
  received_at: timestamp; // ingestion time
}
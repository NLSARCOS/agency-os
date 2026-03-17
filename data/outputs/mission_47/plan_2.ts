// @agency-os/analytics-client
class MissionTracker {
  constructor(apiKey: string, studioId: string) {}
  
  async reportProgress(missionId: string, data: ProgressData) {}
  async checkpoint(name: string, percent: number) {}
}
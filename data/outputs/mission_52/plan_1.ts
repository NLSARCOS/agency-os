// Pseudo-test
for (const role of roles) {
  for (const resource of resources) {
    expect(await canAccess(role, resource)).toBe(expectedMatrix[role][resource]);
  }
}
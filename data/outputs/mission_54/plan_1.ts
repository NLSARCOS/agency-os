// hooks/usePipelineData.ts
export function usePipelineData(pipelineId: string) {
  return useQuery({
    queryKey: ['pipeline', pipelineId],
    queryFn: () => fetchPipeline(pipelineId),
    staleTime: 1000 * 30, // 30s
    refetchOnWindowFocus: false
  });
}

export function useMoveOpportunity() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: moveOpportunity,
    onMutate: async ({ oppId, newStage }) => {
      // Optimistic update
      await queryClient.cancelQueries({ queryKey: ['pipeline'] });
      const previous = queryClient.getQueryData(['pipeline']);
      
      queryClient.setQueryData(['pipeline'], (old) => ({
        ...old,
        opportunities: old.opportunities.map(o => 
          o.id === oppId ? { ...o, stageId: newStage } : o
        )
      }));
      
      return { previous };
    },
    onError: (err, vars, context) => {
      queryClient.setQueryData(['pipeline'], context.previous);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['pipeline'] });
    }
  });
}
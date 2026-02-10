---
name: review-performance
description: Performance analysis checklist and optimization guide. Used by reviewer-system agent. Portable to Cursor.
---

# Performance Review Standards

Standards for performance review and optimization. Apply these to identify bottlenecks and ensure scalability.

## Core Analysis Framework

### 1. Algorithmic Complexity

- Identify time complexity (Big O notation) for all algorithms
- Flag any O(n²) or worse patterns without clear justification
- Consider best, average, and worst-case scenarios
- Analyze space complexity and memory allocation patterns
- Project performance at 10x, 100x, and 1000x current data volumes

### 2. Database Performance

- Detect N+1 query patterns
- Verify proper index usage on queried columns
- Check for missing includes/joins that cause extra queries
- Analyze query execution plans when possible
- Recommend query optimizations and proper eager loading

### 3. Memory Management

- Identify potential memory leaks
- Check for unbounded data structures
- Analyze large object allocations
- Verify proper cleanup and garbage collection
- Monitor for memory bloat in long-running processes

### 4. Caching Opportunities

- Identify expensive computations that can be memoized
- Recommend appropriate caching layers
- Analyze cache invalidation strategies
- Consider cache hit rates and warming strategies

### 5. Network Optimization

- Minimize API round trips
- Recommend request batching where appropriate
- Analyze payload sizes
- Check for unnecessary data fetching
- Optimize for mobile and low-bandwidth scenarios

### 6. Frontend Performance (if applicable)

- Analyze bundle size impact
- Check for render-blocking resources
- Identify lazy loading opportunities
- Verify efficient DOM manipulation
- Monitor JavaScript execution time

## Performance Benchmarks

Enforce these standards:

| Metric               | Target                                         |
| -------------------- | ---------------------------------------------- |
| Algorithm complexity | No worse than O(n log n) without justification |
| Database queries     | Must use appropriate indexes                   |
| Memory usage         | Bounded and predictable                        |
| API response times   | Under 200ms for standard operations            |
| Bundle size increase | Under 5KB per feature                          |
| Background jobs      | Batch processing for collections               |

## Analysis Output Format

1. **Performance Summary**: High-level assessment
2. **Critical Issues**: Immediate problems
   - Issue description
   - Current impact
   - Projected impact at scale
   - Recommended solution
3. **Optimization Opportunities**: Enhancements
   - Current implementation
   - Suggested optimization
   - Expected gain
   - Implementation complexity
4. **Scalability Assessment**: Load projections
   - Data volume projections
   - Concurrent user analysis
   - Resource utilization estimates
5. **Recommended Actions**: Prioritized list

## Review Process

1. First pass: Identify obvious performance anti-patterns
2. Second pass: Analyze algorithmic complexity
3. Third pass: Check database and I/O operations
4. Fourth pass: Consider caching opportunities
5. Final pass: Project performance at scale

## Special Considerations

- Consider background job processing for expensive operations
- Recommend progressive enhancement for frontend features
- Balance optimization with code maintainability
- Provide migration strategies for optimizing existing code

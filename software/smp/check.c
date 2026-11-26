/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

enum { N = 4, ROUNDS = 1024 };
static pthread_barrier_t start;
static _Alignas(64) atomic_uint turn, arrivals;
static uint64_t value; /* release/acquire of turn passes exclusive ownership */
static uint64_t step(uint64_t x,unsigned t){return (x^(t+0x9e37u))*UINT64_C(0x100000001b3);}
static void *worker(void *arg){
    unsigned id=(unsigned)(uintptr_t)arg; cpu_set_t mask; CPU_ZERO(&mask);CPU_SET(id,&mask);
    if(pthread_setaffinity_np(pthread_self(),sizeof mask,&mask)||sched_getcpu()!=(int)id)_Exit(10);
    atomic_fetch_or(&arrivals,1u<<id);int r=pthread_barrier_wait(&start);
    if(r && r!=PTHREAD_BARRIER_SERIAL_THREAD)_Exit(11);
    for(unsigned t=id;t<N*ROUNDS;t+=N){
        while(atomic_load_explicit(&turn,memory_order_acquire)!=t)sched_yield();
        value=step(value,t);atomic_store_explicit(&turn,t+1,memory_order_release);
    }
    if(sched_getcpu()!=(int)id)_Exit(12);
    return NULL;
}
int main(void){
    alarm(45);cpu_set_t mask;CPU_ZERO(&mask);if(sched_getaffinity(0,sizeof mask,&mask)||CPU_COUNT(&mask)!=N)return 2;
    for(unsigned i=0;i<N;i++)if(!CPU_ISSET(i,&mask))return 3;
    pthread_t th[N];if(pthread_barrier_init(&start,NULL,N))return 4;
    for(unsigned i=0;i<N;i++)if(pthread_create(&th[i],NULL,worker,(void*)(uintptr_t)i))return 5;
    for(unsigned i=0;i<N;i++)if(pthread_join(th[i],NULL))return 6;
    uint64_t ref=0;for(unsigned t=0;t<N*ROUNDS;t++)ref=step(ref,t);
    if(atomic_load(&arrivals)!=15||atomic_load(&turn)!=N*ROUNDS||value!=ref)return 7;
    puts("QUAD_SMP_PASS pinned=0,1,2,3 workers=4 shared_handoffs=4096");return 0;
}

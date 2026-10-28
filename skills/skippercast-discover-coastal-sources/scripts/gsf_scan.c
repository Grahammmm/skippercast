/* Thin bounded adapter to the upstream LGPL-2.1 GSF API, not a binary parser.
 * Compile with the six pinned upstream GSF sources; never indexed access.
 * argv: FILE CURSOR NEW_RECORDS PINGS BEAMS READ_BYTES WEST SOUTH EAST NORTH DEADLINE_UNIX
 * Reconstruct state through bounded sequential replay; no index or raw seek.
 * --fixture FILE writes a synthetic fixture through upstream gsfWrite only.
 */
#include "gsf.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <signal.h>
#include <sys/time.h>
extern int gsfError;
/* Count requested bytes, conservatively including short/EOF reads and replay.
 * --wrap=fread binds upstream object calls too; no read beyond the reservation. */
static unsigned long long read_cap=250000000, read_charged=0;
static int read_limit_hit=0;
static FILE *unbuffered_stream=NULL;
size_t __real_fread(void *,size_t,size_t,FILE *);
size_t __wrap_fread(void *ptr,size_t size,size_t count,FILE *stream) {
    if(unbuffered_stream!=stream){if(setvbuf(stream,NULL,_IONBF,0)){read_limit_hit=1;return 0;}unbuffered_stream=stream;}
    if(size && count>(read_cap-read_charged)/size){read_limit_hit=1;return 0;}
    read_charged+=(unsigned long long)size*count;
    return __real_fread(ptr,size,count,stream);
}

static void js(const char *s) {
    putchar('"');
    for (const unsigned char *p=(const unsigned char *)s; *p; ++p) {
        if (*p=='"' || *p=='\\') printf("\\%c",*p);
        else if (*p < 32 || *p > 126) printf("\\u%04x",*p);
        else putchar(*p);
    }
    putchar('"');
}
static long limit(const char *s,long max) {
    char *e; errno=0; long v=strtol(s,&e,10);
    if(errno || *e || v<1 || v>max) return -1;
    return v;
}
static int fixture(const char *path, long prefix) {
    int h; gsfRecords r; gsfDataID id; memset(&r,0,sizeof r); memset(&id,0,sizeof id);
    if(gsfOpen(path,GSF_CREATE,&h)) return 2;
    id.recordID=GSF_RECORD_PROCESSING_PARAMETERS;
    r.process_parameters.number_parameters=1;
    r.process_parameters.param[0]="VERTICAL_DATUM=UNKNOWN";
    r.process_parameters.param_size[0]=(short)(strlen(r.process_parameters.param[0])+1);
    for(long i=0;i<prefix;i++) if(gsfWrite(h,&id,&r)<0) {gsfClose(h);return 2;}
    memset(&r,0,sizeof r); id.recordID=GSF_RECORD_SWATH_BATHYMETRY_PING;
    double depth[4]={0,20,30,40}; unsigned char flags[4]={0,GSF_IGNORE_BEAM,0,0};
    r.mb_ping.number_beams=4; r.mb_ping.depth=depth; r.mb_ping.beam_flags=flags;
    r.mb_ping.latitude=33.4; r.mb_ping.longitude=-118.4; r.mb_ping.ping_time.tv_sec=1625270400;
    r.mb_ping.sensor_id=GSF_SWATH_BATHY_SUBRECORD_UNKNOWN;
    if(gsfLoadScaleFactor(&r.mb_ping.scaleFactors,GSF_SWATH_BATHY_SUBRECORD_DEPTH_ARRAY,0,0.01,0)) {gsfClose(h);return 2;}
    for(int i=0;i<4;i++) {
        if(i==1) {
            depth[1]=21.2; depth[2]=31.2; depth[3]=41.2;
            if(gsfLoadScaleFactor(&r.mb_ping.scaleFactors,GSF_SWATH_BATHY_SUBRECORD_DEPTH_ARRAY,0,0.1,0))return 2;
        }
        r.mb_ping.ping_time.tv_sec++; r.mb_ping.ping_flags=i==2?GSF_IGNORE_PING:0;
        if(gsfWrite(h,&id,&r)<0) {fprintf(stderr,"fixture gsf error %d\n",gsfError);gsfClose(h);return 2;}
    }
    return gsfClose(h)?2:0;
}
int main(int argc,char **argv) {
    if(argc==4 && !strcmp(argv[1],"--fixture")) {long prefix=limit(argv[3],80000);return prefix<0?2:fixture(argv[2],prefix);}
    if(argc!=12) return 2;
    char *deadline_end;double deadline=strtod(argv[11],&deadline_end);struct timeval now;
    gettimeofday(&now,NULL);double remaining=deadline-(now.tv_sec+now.tv_usec/1000000.0);
    if(*deadline_end||!isfinite(deadline)||remaining<=0||remaining>46)return 2;
    signal(SIGALRM,SIG_DFL);struct itimerval timer={{0,0},{(time_t)remaining,(suseconds_t)((remaining-floor(remaining))*1000000)}};
    if(setitimer(ITIMER_REAL,&timer,NULL))return 2;
    char *end; errno=0; long cursor=strtol(argv[2],&end,10);
    if(errno||*end||cursor<0||cursor>80000)return 2;
    long nr=limit(argv[3],10000),np=limit(argv[4],2000),nb=limit(argv[5],1000000),cap=limit(argv[6],250000000);
    if(cap<0)return 2;read_cap=(unsigned long long)cap;
    double box[4];
    for(int i=0;i<4;i++){char *e; box[i]=strtod(argv[i+7],&e);if(*e||!isfinite(box[i]))return 2;}
    if(nr<0||np<0||nb<0||box[0]>=box[2]||box[1]>=box[3])return 2;
    int h; gsfRecords r; gsfDataID id; memset(&r,0,sizeof r);memset(&id,0,sizeof id);
    if(gsfOpen(argv[1],GSF_READONLY,&h)) {printf("{\"status\":\"decode_error\",\"gsf_error\":%d}\n",gsfError);return 2;}
    long replayed=0;
    long records=0,pings=0,beams=0,selected=0,finite=0,valid=0,ignored=0,missing_flags=0,missing_depth=0;
    double min=0,max=0,sum=0,nav[4]={180,90,-180,-90};
    char params[16][257];int nparams=0,params_truncated=0;const char *stop="record_limit";int error=0;
    while(replayed<cursor) {
        int bytes=gsfRead(h,GSF_NEXT_RECORD,&id,&r,NULL,0);
        if(bytes<0){error=gsfError?gsfError:-1;stop=read_limit_hit?"replay_read_budget":"replay_incomplete";break;}
        replayed++;
    }
    while(!error && records<nr) {
        int bytes=gsfRead(h,GSF_NEXT_RECORD,&id,&r,NULL,0);
        if(bytes<0){if(read_limit_hit){stop="read_budget";error=-2;}else if(gsfError==GSF_READ_TO_END_OF_FILE)stop="eof";else{stop="decode_error";error=gsfError;}break;}
        /* A decoded ping is either wholly committed or left for the next chunk. */
        if(id.recordID==GSF_RECORD_SWATH_BATHYMETRY_PING) {
            int n=r.mb_ping.number_beams;
            if(n<0){stop="decode_error";error=-1;break;}
            if(n>nb){stop="ping_exceeds_beam_limit";error=-3;break;}
            if(pings>=np){stop="ping_limit";break;}
            if(beams+n>nb){stop="beam_limit_before_ping";break;}
        }
        records++;
        if(id.recordID==GSF_RECORD_PROCESSING_PARAMETERS) {
            int count=r.process_parameters.number_parameters;
            if(count<0||count>GSF_MAX_PROCESSING_PARAMETERS){error=-1;stop="decode_error";break;}
            for(int i=0;i<count;i++) {
                if(nparams>=16){params_truncated=1;break;}
                int n=r.process_parameters.param_size[i];
                if(n<0||!r.process_parameters.param[i]){params_truncated=1;continue;}
                if(n>256){n=256;params_truncated=1;}memcpy(params[nparams],r.process_parameters.param[i],(size_t)n);params[nparams][n]=0;nparams++;
            }
        }
        if(id.recordID!=GSF_RECORD_SWATH_BATHYMETRY_PING)continue;
        pings++;gsfSwathBathyPing *p=&r.mb_ping;
        if(p->number_beams<0){error=-1;stop="decode_error";break;}
        double x=p->longitude,y=p->latitude;
        int inside=isfinite(x)&&isfinite(y)&&x>=box[0]&&x<=box[2]&&y>=box[1]&&y<=box[3];
        if(inside){selected++;if(x<nav[0])nav[0]=x;if(y<nav[1])nav[1]=y;if(x>nav[2])nav[2]=x;if(y>nav[3])nav[3]=y;}
        if(inside&&!p->depth)missing_depth++;
        if(inside&&!p->beam_flags)missing_flags+=p->number_beams;
        for(int i=0;i<p->number_beams&&beams<nb;i++,beams++) {
            if(!inside||!p->depth||!isfinite(p->depth[i]))continue;
            finite++;
            /* Nonzero application-specific flags remain unknown, not good. */
            if(!p->beam_flags || p->ping_flags || p->beam_flags[i]){ignored++;continue;}
            double z=p->depth[i];if(!valid||z<min)min=z;if(!valid||z>max)max=z;sum+=z;valid++;
        }
        if(beams>=nb){stop="beam_limit";break;}
        if(pings>=np){stop="ping_limit";break;}
    }
    gsfClose(h);
    printf("{\"schema\":\"gsf-resume-chunk-v1\",\"status\":\"%s\",\"gsf_error\":%d,\"stop\":",error?"decode_error":"ok",error);js(stop);
    printf(",\"cursor_start\":%ld,\"cursor_end\":%ld,\"replayed_records\":%ld,\"fread_requested_bytes\":%llu",cursor,cursor+records,replayed,read_charged);
    printf(",\"records\":%ld,\"pings\":%ld,\"beams_scanned\":%ld,\"selected_navigation_pings\":%ld,\"finite_depth_count\":%ld,\"valid_depth_count\":%ld,\"ignored_or_unknown_count\":%ld,\"missing_beam_flags\":%ld,\"missing_depth_pings\":%ld,\"depth_units\":\"metres (GSF API contract)\",\"navigation_units\":\"degrees (GSF API contract)\",\"navigation_bbox\":",records,pings,beams,selected,finite,valid,ignored,missing_flags,missing_depth);
    if(selected)printf("[%.15g,%.15g,%.15g,%.15g]",nav[0],nav[1],nav[2],nav[3]);else printf("null");
    printf(",\"minimum\":");if(valid)printf("%.15g",min);else printf("null");
    printf(",\"maximum\":");if(valid)printf("%.15g",max);else printf("null");
    printf(",\"mean\":");if(valid)printf("%.15g",sum/valid);else printf("null");
    printf(",\"processing_parameters\":[");for(int i=0;i<nparams;i++){if(i)putchar(',');js(params[i]);}
    printf("],\"parameters_truncated\":%s,\"crs\":null,\"vertical_datum\":null,\"grid_resolution\":null,\"sounding_support\":null}\n",params_truncated?"true":"false");
    return error?2:0;
}

import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild } from '@angular/core';

@Component({
  selector: 'app-canva-anime',
  templateUrl: './canva-anime.component.html',
  styleUrls: ['./canva-anime.component.scss']
})
export class CanvaAnimeComponent implements AfterViewInit, OnDestroy {

  @ViewChild('myCanvas', { static: true })
  canvasRef!: ElementRef<HTMLCanvasElement>;

  private ctx!: CanvasRenderingContext2D;
  private animationId: number = 0;

  private points: any[] = [];

  private vx = 0.5;
  private vy = 0.5;

  private POINTS = 50;

  ngAfterViewInit(): void {
    this.initCanvas();
    this.createPoints();
    this.animate();

    window.addEventListener('resize', this.resizeCanvas);
  }

  /* ================= INIT ================= */

  private initCanvas(): void {

    const canvas = this.canvasRef.nativeElement;

    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    this.ctx = canvas.getContext('2d')!;
  }


  /* ================= RESIZE ================= */

  private resizeCanvas = (): void => {
    this.initCanvas();
  };


  /* ================= CREATE POINTS ================= */

  private createPoints(): void {

    this.points = [];

    const canvas = this.canvasRef.nativeElement;

    for (let i = 0; i < this.POINTS; i++) {

      const x = Math.random() * canvas.width;
      const y = Math.random() * canvas.height;

      let xVel = this.vx;
      let yVel = this.vy;

      if (i % 2 === 0) xVel += 0.5;
      else yVel += 0.5;

      this.points.push({
        x,
        y,
        originx: x,
        originy: y,
        vx: xVel,
        vy: yVel,
        closest: null
      });
    }

    this.findClosest();
  }


  /* ================= DISTANCE ================= */

  private distance(p1: any, p2: any): number {
    return Math.abs(p1.x - p2.x) + Math.abs(p1.y - p2.y);
  }


  /* ================= CLOSEST ================= */

  private findClosest(): void {

    for (let i = 0; i < this.points.length; i++) {

      let closest: any;

      const p1 = this.points[i];

      for (let j = 0; j < this.points.length; j++) {

        const p2 = this.points[j];

        if (p1 !== p2) {

          if (!closest ||
              this.distance(p1, p2) < this.distance(p1, closest)) {
            closest = p2;
          }
        }
      }

      p1.closest = closest;
    }
  }


  /* ================= DRAW POINT ================= */

  private drawPoint(p: any): void {

    this.ctx.beginPath();

    this.ctx.arc(p.x, p.y, 2, 0, Math.PI * 2);

    this.ctx.fillStyle = '#00000';

    this.ctx.fill();

    this.ctx.beginPath();

    this.ctx.moveTo(p.x, p.y);

    this.ctx.lineTo(p.closest.x, p.closest.y);

    this.ctx.strokeStyle = 'rgba(255,255,255,0.12)';

    this.ctx.stroke();
  }


  /* ================= ANIMATION ================= */

  private animate = (): void => {

    const canvas = this.canvasRef.nativeElement;

    this.ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (let i = 0; i < this.POINTS; i++) {

      const p = this.points[i];

      this.drawPoint(p);

      p.x += p.vx;
      p.y += p.vy;

      if (p.y + p.vy > p.originy + 20 ||
          p.y + p.vy < p.originy - 20) {
        p.vy *= -1;
      }

      if (p.x + p.vx > p.originx + 20 ||
          p.x + p.vx < p.originx - 20) {
        p.vx *= -1;
      }
    }

    this.animationId = requestAnimationFrame(this.animate);
  };


  /* ================= DESTROY ================= */

  ngOnDestroy(): void {

    cancelAnimationFrame(this.animationId);

    window.removeEventListener('resize', this.resizeCanvas);
  }

}
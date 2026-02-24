import { Component, ElementRef, ViewChild, AfterViewInit, HostListener, Inject, PLATFORM_ID } from '@angular/core';
import { isPlatformBrowser } from '@angular/common';

interface GridCell {
  x: number;
  y: number;
  alpha: number;
  fading: boolean;
  lastTouched: number;
}

@Component({
  selector: 'app-animatebg',
  templateUrl: './animatebg.component.html',
  styleUrls: ['./animatebg.component.scss']
})
export class AnimatebgComponent implements AfterViewInit {

  @ViewChild('gridCanvas', { static: false })
  canvasRef!: ElementRef<HTMLCanvasElement>;

  private ctx!: CanvasRenderingContext2D;
  private width = 0;
  private height = 0;

  private mouse = { x: -9999, y: -9999 };
  private squareSize = 80;
  private grid: GridCell[] = [];

  private isBrowser = false;
  private animationId: number | null = null;

  constructor(
    @Inject(PLATFORM_ID) private platformId: Object
  ) {
    this.isBrowser = isPlatformBrowser(this.platformId);
  }

  ngAfterViewInit(): void {

    // ❗ Stop on server
    if (!this.isBrowser) return;

    const canvas = this.canvasRef.nativeElement;

    const context = canvas.getContext('2d');

    if (!context) return;

    this.ctx = context;

    this.setCanvasSize();
    this.initGrid();
    this.startAnimation();
  }

  private setCanvasSize(): void {

    if (!this.isBrowser) return;

    const canvas = this.canvasRef.nativeElement;

    this.width = canvas.width = window.innerWidth;
    this.height = canvas.height = window.innerHeight;
  }

  private initGrid(): void {

    if (!this.isBrowser) return;

    this.grid = [];

    for (let x = 0; x < this.width; x += this.squareSize) {
      for (let y = 0; y < this.height; y += this.squareSize) {
        this.grid.push({
          x,
          y,
          alpha: 0,
          fading: false,
          lastTouched: 0
        });
      }
    }
  }

  private getCellAt(x: number, y: number): GridCell | undefined {

    if (!this.isBrowser) return;

    return this.grid.find(cell =>
      x >= cell.x &&
      x < cell.x + this.squareSize &&
      y >= cell.y &&
      y < cell.y + this.squareSize
    );
  }

  @HostListener('window:resize')
  onResize(): void {

    if (!this.isBrowser) return;

    this.setCanvasSize();
    this.initGrid();
  }

@HostListener('window:mousemove', ['$event'])
onMouseMove(event: MouseEvent): void {
  if (!this.isBrowser) return;
  const target = event.target as HTMLElement;
  if (target.closest('.no-animation')) {
    return;
  }
  this.mouse.x = event.clientX;
  this.mouse.y = event.clientY;
  const cell = this.getCellAt(this.mouse.x, this.mouse.y);
  if (cell && cell.alpha === 0) {
    cell.alpha = 1;
    cell.lastTouched = Date.now();
    cell.fading = false;
  }
}


  private startAnimation(): void {

    if (!this.isBrowser) return;

    const draw = () => {

      const now = Date.now();

      this.ctx.clearRect(0, 0, this.width, this.height);

      for (const cell of this.grid) {

        if (cell.alpha > 0 && !cell.fading && now - cell.lastTouched > 500) {
          cell.fading = true;
        }

        if (cell.fading) {
          cell.alpha -= 0.02;

          if (cell.alpha <= 0) {
            cell.alpha = 0;
            cell.fading = false;
          }
        }

        if (cell.alpha > 0) {

          const centerX = cell.x + this.squareSize / 2;
          const centerY = cell.y + this.squareSize / 2;

          const gradient = this.ctx.createRadialGradient(
            centerX, centerY, 5,
            centerX, centerY, this.squareSize
          );

          gradient.addColorStop(0, `rgba(0, 255, 204, ${cell.alpha})`);
          gradient.addColorStop(1, `rgba(0, 255, 204, 0)`);

          this.ctx.strokeStyle = gradient;
          this.ctx.lineWidth = 1.3;

          this.ctx.strokeRect(
            cell.x + 0.5,
            cell.y + 0.5,
            this.squareSize - 1,
            this.squareSize - 1
          );
        }
      }

      this.animationId = requestAnimationFrame(draw);
    };

    draw();
  }

  ngOnDestroy(): void {

    // Stop animation on destroy
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
    }
  }
}

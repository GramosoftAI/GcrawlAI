import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CanvaAnimeComponent } from './canva-anime.component';

describe('CanvaAnimeComponent', () => {
  let component: CanvaAnimeComponent;
  let fixture: ComponentFixture<CanvaAnimeComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [CanvaAnimeComponent]
    });
    fixture = TestBed.createComponent(CanvaAnimeComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

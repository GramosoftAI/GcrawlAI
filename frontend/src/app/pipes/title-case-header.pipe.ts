import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
  name: 'titleCaseHeader'
})
export class TitleCaseHeaderPipe implements PipeTransform {

  transform(value: string): string {
    if (!value) return '';

    return value
      .replace(/_/g, ' ')
      .split(' ')
      .map(word =>
        word.charAt(0).toUpperCase() +
        word.slice(1).toLowerCase()
      )
      .join(' ');
  }
}
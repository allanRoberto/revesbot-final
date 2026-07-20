import styles from './triggers.module.css';

export default function Loading() {
  return (
    <main className={styles.page}>
      <div className={styles.loadingGrid}>{[0, 1, 2].map((item) => <div key={item} />)}</div>
    </main>
  );
}
